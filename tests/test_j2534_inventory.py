from guzzionboard.j2534 import inventory
from guzzionboard.server import Api, ROUTES_GET
from guzzionboard.workstation import Workstation


class Key:
    def __init__(self, path): self.path = path
    def __enter__(self): return self
    def __exit__(self, *args): pass


class Registry:
    HKEY_LOCAL_MACHINE = object()
    KEY_READ = 1
    KEY_WOW64_32KEY = 2
    KEY_WOW64_64KEY = 4
    def __init__(self): self.opens = []
    def OpenKey(self, root, path, reserved, flags):
        self.opens.append((path, flags))
        if isinstance(root, Key): return Key(root.path + '/' + path)
        if '04.04' in path and flags & self.KEY_WOW64_32KEY: return Key(path)
        raise FileNotFoundError(path)
    def EnumKey(self, root, index):
        if index == 0: return 'Example VCI'
        error = OSError('no more')
        error.winerror = 259
        raise error
    def QueryValueEx(self, key, name):
        values = {'FunctionLibrary': r'C:\\vci.dll', 'ISO14230': 1, 'CAN': 0}
        if name not in values: raise FileNotFoundError(name)
        return values[name], 1


def test_inventory_is_registry_only_and_keeps_claims_and_bitness():
    reg = Registry()
    report = inventory(system='Windows', registry=reg)
    assert len(reg.opens) == 5
    assert report['errors'] == []
    device = report['devices'][0]
    assert device['registry_view_bits'] == 32
    assert device['version'] == '04.04'
    assert device['protocol_claims'] == {'CAN': 0, 'ISO14230': 1}
    assert device['library'].endswith('vci.dll')
    assert 'not loaded' in report['note']


def test_no_windows_registry_access_on_other_platforms():
    reg = Registry()
    report = inventory(system='Linux', registry=reg)
    assert not reg.opens and not report['devices']
    assert 'unavailable' in report['note']


def test_j2534_endpoint_is_read_only(tmp_path, monkeypatch):
    from guzzionboard import server
    monkeypatch.setattr(server.j2534, 'inventory', lambda: {'devices': [], 'note': 'test'})
    assert ROUTES_GET['/api/adapter/j2534'] == 'get_j2534'
    status, data = Api(Workstation(session_dir=tmp_path)).get_j2534({})
    assert status == 200 and data['devices'] == []
