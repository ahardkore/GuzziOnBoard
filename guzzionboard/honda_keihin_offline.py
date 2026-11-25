"""Offline, SHA-256-pinned Honda Keihin calibration checksum providers.

Adapted from aeaphichart/HondaECU-1 at b59ae98baf092def23d7c34d5ef5f43bd6aba952
(GPL-3.0; see LICENSES/HondaECU-GPL-3.0.txt and docs/XDF_LIBRARY.md).

Every provider operates strictly on local binary images that match both the
pinned adapted ``*_gob.xdf`` SHA-256 and one of the pinned repository stock
calibration SHA-256 digests. No ECU communication or programming is performed.
"""
from __future__ import annotations

from dataclasses import dataclass

from .checksums import ChecksumProvider, ChecksumUnavailable
from .tuning import TuningError

UPSTREAM_SOURCE = (
    "https://github.com/aeaphichart/HondaECU-1/tree/"
    "b59ae98baf092def23d7c34d5ef5f43bd6aba952"
)


@dataclass
class HondaOfflineSpec:
    family: str
    xdf_name: str
    xdf_sha256: str
    ecu_id: str
    provider_id: str
    provider_name: str
    checksum_name: str
    image_size: int
    checksum_offset: int
    years: tuple[int, ...]
    accepted_models: tuple[str, ...]
    accepted_ecu_ids: tuple[str, ...]
    stock_sha256s: dict[str, str]
    note: str


SPECS: dict[str, HondaOfflineSpec] = {
    "CBR1000RR-MEL": HondaOfflineSpec(
        family="CBR1000RR-MEL",
        xdf_name="CBR1000RR_MEL_gob.xdf",
        xdf_sha256="6e9a948646094ae3041374023dfebf8169059bfd25ea7b702366c7a2e6e20cd8",
        ecu_id="honda_cbr1000rr_mel",
        provider_id="honda-cbr1000rr-mel-v1",
        provider_name="Honda CBR1000RR 2006-2007 MEL checksum",
        checksum_name="Honda MEL checksum",
        image_size=0x40000,
        checksum_offset=0x3FFF8,
        years=(2006, 2007),
        accepted_models=("CBR1000RR (MEL)", "CBR1000RR"),
        accepted_ecu_ids=("honda_cbr1000rr_mel", "honda_pgmfi_research"),
        stock_sha256s={
            "38770-MEL-A21": "e2e19d2538703c2a5a4686eccfa40375c2a17219f8a99baf8be8e39557a494f5",
            "38770-MEL-A22": "d1edd38e143fccb6b48076c1b4570774b44cd2d732eefaf0e2a3de0675cb0b7b",
            "38770-MEL-D21": "78d71007c90e66e38293afba3cae4ce07464d5b3e7baea152bb881a9e5cd3611",
            "38770-MEL-F21": "304d2bd9631c4da27af028b49bcc51a648a9b44a5a53cce850a6d101114e8c1f",
            "38770-MEL-L22": "060310a2243a27886ca921795969591f99ebd6edb17308a0a7f7644cae8bbafa",
        },
        note=(
            "Pinned CBR1000RR_MEL_gob.xdf and HondaECU 38770-MEL-A21/A22/D21/F21/L22 "
            "256 KiB stock images only; offline only, no hardware validation."
        ),
    ),
    "CB500-MJW": HondaOfflineSpec(
        family="CB500-MJW",
        xdf_name="CB500_MJW_gob.xdf",
        xdf_sha256="05ff5586cd5af3ac70ff6edd9ba64d201f64d05d9c71cdbaff0d4c99ae1fcc54",
        ecu_id="honda_cb500_mjw",
        provider_id="honda-cb500-mjw-v1",
        provider_name="Honda CB500 / CBR500 2017-2018 MJW checksum",
        checksum_name="Honda MJW checksum",
        image_size=0x40000,
        checksum_offset=0x3FFF8,
        years=(2017, 2018),
        accepted_models=(
            "CBR500R (MJW)", "CB500F (MJW)", "CB500X (MJW)",
            "CBR500R", "CB500F", "CB500X",
        ),
        accepted_ecu_ids=("honda_cb500_mjw", "honda_pgmfi_research"),
        stock_sha256s={
            "38770-MJW-AQ1": "03528147cc0454667b007824e1da464f3d1ef65cf212d07abc8650109bd36dd8",
            "38770-MJW-DR1": "d10daaa3ff2baeb9d5fc4ef899d098f4a9b7c3d8e0a8dbc57e2c710859c412cd",
        },
        note=(
            "Pinned CB500_MJW_gob.xdf and HondaECU 38770-MJW-AQ1/DR1 256 KiB "
            "stock images only (38770-MJW-T11 excluded: layout incompatible); "
            "offline only, no hardware validation."
        ),
    ),
    "CRF110F-KYK-D12": HondaOfflineSpec(
        family="CRF110F-KYK-D12",
        xdf_name="CRF110F_KYK_D12_gob.xdf",
        xdf_sha256="134c58736f713d283cbe8f496ace6a60ecd9ac90cc848b5a9c41824ed5511033",
        ecu_id="honda_crf110f_kyk",
        provider_id="honda-crf110f-kyk-d12-v1",
        provider_name="Honda CRF110F 2019-2024 KYK-D12 checksum",
        checksum_name="Honda KYK-D12 checksum",
        image_size=0x10000,
        checksum_offset=0x0000,
        years=(2019, 2020, 2021, 2022, 2023, 2024),
        accepted_models=("CRF110F (KYK-D12)", "CRF110F", "CRF 110 F"),
        accepted_ecu_ids=("honda_crf110f_kyk", "honda_pgmfi_research"),
        stock_sha256s={
            "38770-KYK-D12": "33a0ab747586c873d4e126bd3491410c4a236da589cdeb4b314e95680f565f58",
        },
        note=(
            "Pinned CRF110F_KYK_D12_gob.xdf and HondaECU 38770-KYK-D12 64 KiB "
            "stock image only (checksum byte at 0x0000); offline only, no hardware validation."
        ),
    ),
    "MSX125-K26-911": HondaOfflineSpec(
        family="MSX125-K26-911",
        xdf_name="MSX125_K26_911_gob.xdf",
        xdf_sha256="3753460641a6aa64b2b2d0114a1efb81c68ce8a6324746b8a082e4dcbd6206ba",
        ecu_id="honda_msx125_k26_911",
        provider_id="honda-msx125-k26-911-v1",
        provider_name="Honda MSX125 / Grom 2013-2015 K26-911/931 checksum",
        checksum_name="Honda K26-911 checksum",
        image_size=0xC000,
        checksum_offset=0x0000,
        years=(2013, 2014, 2015),
        accepted_models=(
            "MSX125 / Grom (K26-911)", "MSX125", "MSX125 GROM", "Grom / MSX 125",
        ),
        accepted_ecu_ids=("honda_msx125_k26_911", "honda_pgmfi_research"),
        stock_sha256s={
            "38770-K26-911": "0f63297e3dce62ae9ce8aaec0652a03c0df77963d71720db5f573ea185329fa3",
            "38770-K26-931": "1389e3c467bd2c0644d2a39f56198b3a4f3c155a04e202a1f4f08b9895e27f09",
        },
        note=(
            "Pinned MSX125_K26_911_gob.xdf and HondaECU 38770-K26-911/931 48 KiB "
            "stock images only (checksum byte at 0x0000); offline only, no hardware validation."
        ),
    ),
    "MSX125-K26-B13": HondaOfflineSpec(
        family="MSX125-K26-B13",
        xdf_name="MSX125_K26_B13_gob.xdf",
        xdf_sha256="7de3a66dc09c071cc5f59afcce3b2982066c5453ff8291f9826517db638b0752",
        ecu_id="honda_msx125_k26_sf",
        provider_id="honda-msx125-k26-b13-v1",
        provider_name="Honda MSX125 / Grom SF 2016-2020 K26-B13 checksum",
        checksum_name="Honda K26-B13 checksum",
        image_size=0x10000,
        checksum_offset=0x0000,
        years=(2016, 2017, 2018, 2019, 2020),
        accepted_models=(
            "MSX125 / Grom SF (K26-B13/C31)", "MSX125", "MSX125 GROM", "Grom / MSX 125",
        ),
        accepted_ecu_ids=("honda_msx125_k26_sf", "honda_pgmfi_research"),
        stock_sha256s={
            "38770-K26-B13": "d69d831fb94abd47cbaa0bbc9697b3cbc1e708b3d5a416fe2d55d52017a676dd",
        },
        note=(
            "Pinned MSX125_K26_B13_gob.xdf and HondaECU 38770-K26-B13 64 KiB "
            "stock image only (checksum byte at 0x0000); offline only, no hardware validation."
        ),
    ),
    "MSX125-K26-C31": HondaOfflineSpec(
        family="MSX125-K26-C31",
        xdf_name="MSX125_K26_C31_gob.xdf",
        xdf_sha256="bea344590ea70b1eb9c051c03a5c3dfec9a97a6bbf59fcdde0dc69dddb248310",
        ecu_id="honda_msx125_k26_sf",
        provider_id="honda-msx125-k26-c31-v1",
        provider_name="Honda MSX125 / Grom SF 2016-2020 K26-C31 checksum",
        checksum_name="Honda K26-C31 checksum",
        image_size=0x10000,
        checksum_offset=0x0000,
        years=(2016, 2017, 2018, 2019, 2020),
        accepted_models=(
            "MSX125 / Grom SF (K26-B13/C31)", "MSX125", "MSX125 GROM", "Grom / MSX 125",
        ),
        accepted_ecu_ids=("honda_msx125_k26_sf", "honda_pgmfi_research"),
        stock_sha256s={
            "38770-K26-C31": "0cdf761a4cf26ef16050f4650cf668b59b5c826fccc8878ea3287e776310530b",
        },
        note=(
            "Pinned MSX125_K26_C31_gob.xdf and HondaECU 38770-K26-C31 64 KiB "
            "stock image only (checksum byte at 0x0000); offline only, no hardware validation."
        ),
    ),
    "Z125M-K0F-A01": HondaOfflineSpec(
        family="Z125M-K0F-A01",
        xdf_name="Z125M_K0F_A01_gob.xdf",
        xdf_sha256="ae9d8f7a9d107a19a478a04f339976759dcbe2e54d526d5e46c8e0cc04281946",
        ecu_id="honda_z125m_k0f",
        provider_id="honda-z125m-k0f-a01-v1",
        provider_name="Honda Monkey 125 / Z125M 2018-2021 K0F-A01 checksum",
        checksum_name="Honda K0F-A01 checksum",
        image_size=0x18000,
        checksum_offset=0x0000,
        years=(2018, 2019, 2020, 2021),
        accepted_models=("Monkey 125 / Z125M (K0F-A01)", "Z125M", "Monkey / Z 125"),
        accepted_ecu_ids=("honda_z125m_k0f", "honda_pgmfi_research"),
        stock_sha256s={
            "38770-K0F-A01": "71f3c6eef4229fe0eed69434dacf8082dacf5865b71249f514c6c01d52941def",
        },
        note=(
            "Pinned Z125M_K0F_A01_gob.xdf and HondaECU 38770-K0F-A01 96 KiB "
            "stock image only (checksum byte at 0x0000); offline only, no hardware validation."
        ),
    ),
}


def _check_spec(spec: HondaOfflineSpec, image: bytes, context: dict) -> None:
    allowed_sources = set(spec.stock_sha256s.values())
    if (len(image) != spec.image_size
            or context.get("address_base") != 0
            or context.get("xdf_sha256") != spec.xdf_sha256
            or context.get("source_sha256") not in allowed_sources
            or context.get("declared_checksums") != [spec.checksum_name]):
        parts = ", ".join(sorted(spec.stock_sha256s))
        raise ChecksumUnavailable(
            f"{spec.family} checksum requires pinned {spec.xdf_name} and stock "
            f"image ({parts}), {spec.image_size // 1024} KiB, base 0"
        )
    for change in context.get("changes", []):
        start = int(change["image_offset"], 0)
        length = len(bytes.fromhex(change["after_hex"]))
        if start <= spec.checksum_offset < start + length:
            raise ChecksumUnavailable(
                f"calibration edits may not overlap the {spec.family} checksum byte"
            )


def _make_provider(spec: HondaOfflineSpec) -> ChecksumProvider:
    def update(image: bytes, context: dict) -> bytes:
        _check_spec(spec, image, context)
        output = bytearray(image)
        off = spec.checksum_offset
        output[off] = (-(sum(output) - output[off])) & 0xFF
        return bytes(output)

    def verify(image: bytes, context: dict) -> bool:
        _check_spec(spec, image, context)
        return (sum(image) & 0xFF) == 0

    return ChecksumProvider(
        spec.provider_id,
        spec.provider_name,
        "1.0.0",
        (spec.checksum_name,),
        update,
        verify,
        verified=False,
        note=spec.note,
        source=UPSTREAM_SOURCE,
    )


def providers() -> list[ChecksumProvider]:
    return [_make_provider(spec) for spec in SPECS.values()]


def check_build_fitment(xdf_family: str, xdf_file_sha256: str, image, selection) -> bool:
    """Validate and tag ``image.ecu_id`` if ``xdf_family`` is a pinned Honda Keihin offline family.

    Returns ``True`` when handled, ``False`` if ``xdf_family`` is not one of ``SPECS``.
    Raises ``TuningError`` when the XDF, stock image SHA-256, or selected bike mismatches.
    """
    spec = SPECS.get(xdf_family)
    if spec is None:
        return False
    allowed_sources = set(spec.stock_sha256s.values())
    if (xdf_file_sha256 != spec.xdf_sha256
            or image.sha256 not in allowed_sources
            or image.size != spec.image_size
            or selection.make.lower() != "honda"
            or selection.model not in spec.accepted_models
            or selection.year not in spec.years
            or not selection.profile
            or selection.profile.id not in spec.accepted_ecu_ids
            or (image.ecu_id and image.ecu_id not in spec.accepted_ecu_ids)):
        parts = ", ".join(sorted(spec.stock_sha256s))
        years_label = f"{min(spec.years)}–{max(spec.years)}" if len(spec.years) > 1 else str(spec.years[0])
        raise TuningError(
            f"Honda {spec.family} build requires a matching {spec.accepted_models[0]} "
            f"({years_label}) selection, the pinned {spec.xdf_name} and an exact "
            f"stock image SHA-256 ({parts})"
        )
    image.ecu_id = spec.ecu_id
    return True
