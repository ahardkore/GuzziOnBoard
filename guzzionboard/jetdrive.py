"""Bounded JetDrive multicast observations, not an ECU programming interface.

Wire layout adapted from DynoAI_3 api/services/jetdrive/jetdrive_client.py,
Copyright (c) 2024-2026 DynoAI, MIT, commit cc22636aafa40a0b4ce4c27b5e0cc50795012b87.
See LICENSES/DynoAI-MIT.txt. Integration tests use synthetic packets only.
"""
from __future__ import annotations

import ipaddress
import math
import secrets
import socket
import struct
import time

from .transports.base import TransportError

HEADER = struct.Struct('<BHHBH')
INFO_BLOCK = struct.Struct('<HB30sB')
VALUE_BLOCK = struct.Struct('<HIf')
GROUPS = ('224.0.2.10', '239.255.60.60')
PORT = 22344
WINDOW = 3.0
MAX_PACKETS = 1200
MAX_SAMPLES = 4000
MAX_METADATA = 1000


def _text(data: bytes) -> str:
    return data.split(b'\0', 1)[0].decode('utf-8', 'replace').strip()


def decode(data: bytes) -> dict | None:
    """Decode a complete datagram; unknown keys/partial payloads are ignored."""
    if len(data) < HEADER.size:
        return None
    key, size, provider, seq, dest = HEADER.unpack_from(data)
    if size != len(data) - HEADER.size:
        return None
    payload = data[HEADER.size:]
    base = {'key': key, 'provider': provider, 'seq': seq, 'dest': dest}
    if key == 1:
        if len(payload) < 50 or (len(payload) - 50) % INFO_BLOCK.size:
            return None
        entries = []
        for pos in range(50, len(payload), INFO_BLOCK.size):
            ident, vendor, name, unit = INFO_BLOCK.unpack_from(payload, pos)
            entries.append({'id': ident, 'vendor': vendor, 'name': _text(name), 'unit_code': unit})
        return {**base, 'name': _text(payload[:50]), 'channels': entries}
    if key == 2:
        if not payload or len(payload) % VALUE_BLOCK.size:
            return None
        entries = []
        for pos in range(0, len(payload), VALUE_BLOCK.size):
            ident, timestamp, value = VALUE_BLOCK.unpack_from(payload, pos)
            if math.isfinite(value):
                entries.append({'id': ident, 'timestamp_ms': timestamp, 'value': value})
        return {**base, 'samples': entries}
    if key == 3 and not payload:
        return base
    return None


def observe(group: object, interface: object, request_info: object = False) -> dict:
    if group not in GROUPS:
        raise ValueError('Choose a documented JetDrive multicast group.')
    if not isinstance(interface, str):
        raise ValueError('Enter the local IPv4 interface address or 0.0.0.0.')
    try:
        address = ipaddress.IPv4Address(interface)
    except ipaddress.AddressValueError as exc:
        raise ValueError('Enter the local IPv4 interface address or 0.0.0.0.') from exc
    if address.is_multicast or address.is_reserved or address.is_global:
        raise ValueError('Use a local unicast interface address or 0.0.0.0.')
    if type(request_info) is not bool:
        raise ValueError('Metadata request must be true or false.')
    iface = str(address)
    metadata, samples = {}, []
    packets, invalid, dropped, info_sent = 0, 0, 0, False
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('0.0.0.0', PORT))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                            socket.inet_aton(group) + socket.inet_aton(iface))
            if request_info:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface))
                # Single DynoAI-documented RequestChannelInfo; never a dyno or ECU control command.
                wire = HEADER.pack(6, 0, secrets.randbelow(65534) + 1, 1, 0xffff)
                if sock.sendto(wire, (group, PORT)) != len(wire):
                    raise TransportError('JetDrive metadata request could not be sent completely.')
                info_sent = True
            sock.settimeout(0.2)
            deadline = time.monotonic() + WINDOW
            while time.monotonic() < deadline and packets < MAX_PACKETS and len(samples) < MAX_SAMPLES:
                try:
                    data, source = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                packets += 1
                event = decode(data)
                if event is None:
                    invalid += 1
                    continue
                source_ip = source[0]
                key = (source_ip, event['provider'])
                if event['key'] == 3:
                    metadata.pop(key, None)
                elif event['key'] == 1:
                    if key not in metadata and len(metadata) >= 100:
                        dropped += len(event['channels'])
                        continue
                    provider = metadata.setdefault(key, {'name': '', 'channels': {}})
                    provider['name'] = event['name']
                    for entry in event['channels']:
                        if entry['id'] not in provider['channels'] and sum(len(p['channels']) for p in metadata.values()) >= MAX_METADATA:
                            dropped += 1
                            continue
                        provider['channels'][entry['id']] = entry
                else:
                    provider = metadata.get(key, {})
                    for item in event['samples']:
                        if len(samples) >= MAX_SAMPLES:
                            dropped += 1
                            continue
                        info = provider.get('channels', {}).get(item['id']) or {}
                        samples.append({**item, 'source': source_ip, 'provider': event['provider'],
                                        'sequence': event['seq'], 'provider_name': provider.get('name', ''),
                                        'channel_name': info.get('name', ''), 'unit_code': info.get('unit_code')})
        finally:
            sock.close()
    except OSError as exc:
        raise TransportError(f'JetDrive multicast observation failed: {exc}') from exc
    return {'packets': packets, 'invalid_packets': invalid, 'dropped': dropped,
            'limit_reached': packets >= MAX_PACKETS or len(samples) >= MAX_SAMPLES,
            'metadata_requested': info_sent, 'samples': samples,
            'provider_count': len(metadata), 'synthetic_tested': True}
