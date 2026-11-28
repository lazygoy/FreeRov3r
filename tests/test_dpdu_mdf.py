import pytest

from freerov3r.hardware.dpdu_mdf import (
    DPduDescriptionError,
    map_resource_to_dlc_pins,
    parse_d_pdu_cdf,
    parse_d_pdu_mdf,
)


def _write(path, root):
    path.write_text(root, encoding="utf-8")
    return str(path)


def test_parse_mdf_resolves_resource_bus_protocol_and_pin_ids(tmp_path):
    mdf = _write(tmp_path / "module.xml", """<?xml version="1.0"?>
    <MVCI_MODULE_DESCRIPTION FILE_VERSION="1.2" MVCI_PART2_STANDARD_VERSION="2.2.0">
      <DESCRIPTION>Test module</DESCRIPTION><SUPPLIER_NAME>Test supplier</SUPPLIER_NAME>
      <PINTYPE EID="PIN_HI"><ID>2000</ID><SHORT_NAME>HI</SHORT_NAME></PINTYPE>
      <PINTYPE EID="PIN_LOW"><ID>2001</ID><SHORT_NAME>LOW</SHORT_NAME></PINTYPE>
      <BUSTYPE EID="BUS_CAN"><ID>300</ID><SHORT_NAME>ISO_11898_2_DWCAN</SHORT_NAME></BUSTYPE>
      <PROTOCOL EID="PROTO_UDS"><ID>400</ID><SHORT_NAME>ISO_14229_3_on_ISO_15765_2</SHORT_NAME></PROTOCOL>
      <MODULETYPE><ID>500</ID><SHORT_NAME>VCI_CAN</SHORT_NAME>
        <RESOURCE IDREF="RES_CAN"/>
      </MODULETYPE>
      <RESOURCE EID="RES_CAN"><ID>600</ID><SHORT_NAME>CAN_1</SHORT_NAME>
        <DESCRIPTION>Dual wire CAN</DESCRIPTION>
        <PIN_ON_MODULE><PIN_ON_MODULE>2</PIN_ON_MODULE><PINTYPE IDREF="PIN_HI"/></PIN_ON_MODULE>
        <PIN_ON_MODULE><PIN_ON_MODULE>3</PIN_ON_MODULE><PINTYPE IDREF="PIN_LOW"/></PIN_ON_MODULE>
        <BUSTYPE IDREF="BUS_CAN"/><PROTOCOL IDREF="PROTO_UDS"/>
      </RESOURCE>
    </MVCI_MODULE_DESCRIPTION>""")

    description = parse_d_pdu_mdf(mdf)

    assert description.supplier_name == "Test supplier"
    assert description.file_version == "1.2"
    assert description.bus_types[0].object_id == 300
    assert description.protocols[0].short_name == "ISO_14229_3_on_ISO_15765_2"
    assert description.module_types[0].object_id == 500
    resources = description.resources_for_module_type(500)
    assert len(resources) == 1
    assert resources[0].object_id == 600
    assert [(p.module_pin_number, p.pin_type_id, p.pin_type_name) for p in resources[0].pins] == [
        (2, 2000, "HI"),
        (3, 2001, "LOW"),
    ]


def test_parse_mdf_handles_namespaces(tmp_path):
    mdf = _write(tmp_path / "namespaced.xml", """<m:MVCI_MODULE_DESCRIPTION xmlns:m="urn:test">
      <m:PINTYPE EID="P"><m:ID>1</m:ID><m:SHORT_NAME>K</m:SHORT_NAME></m:PINTYPE>
      <m:BUSTYPE EID="B"><m:ID>2</m:ID><m:SHORT_NAME>KLINE</m:SHORT_NAME></m:BUSTYPE>
      <m:PROTOCOL EID="Q"><m:ID>3</m:ID><m:SHORT_NAME>KWP</m:SHORT_NAME></m:PROTOCOL>
      <m:RESOURCE EID="R"><m:ID>4</m:ID><m:SHORT_NAME>K1</m:SHORT_NAME>
        <m:PIN_ON_MODULE><m:PIN_ON_MODULE>7</m:PIN_ON_MODULE><m:PINTYPE IDREF="P"/></m:PIN_ON_MODULE>
        <m:BUSTYPE IDREF="B"/><m:PROTOCOL IDREF="Q"/>
      </m:RESOURCE>
    </m:MVCI_MODULE_DESCRIPTION>""")

    parsed = parse_d_pdu_mdf(mdf)
    assert parsed.resources[0].pins[0].pin_type_name == "K"


def test_parse_cdf_and_map_resource_pins_to_dlc_pins(tmp_path):
    mdf = _write(tmp_path / "module.xml", """<MVCI_MODULE_DESCRIPTION>
      <PINTYPE EID="HI"><ID>2000</ID><SHORT_NAME>HI</SHORT_NAME></PINTYPE>
      <PINTYPE EID="LOW"><ID>2001</ID><SHORT_NAME>LOW</SHORT_NAME></PINTYPE>
      <BUSTYPE EID="CAN"><ID>300</ID><SHORT_NAME>CAN</SHORT_NAME></BUSTYPE>
      <PROTOCOL EID="UDS"><ID>400</ID><SHORT_NAME>UDS_CAN</SHORT_NAME></PROTOCOL>
      <RESOURCE EID="CAN1"><ID>600</ID><SHORT_NAME>CAN1</SHORT_NAME>
        <PIN_ON_MODULE><PIN_ON_MODULE>2</PIN_ON_MODULE><PINTYPE IDREF="HI"/></PIN_ON_MODULE>
        <PIN_ON_MODULE><PIN_ON_MODULE>3</PIN_ON_MODULE><PINTYPE IDREF="LOW"/></PIN_ON_MODULE>
        <BUSTYPE IDREF="CAN"/><PROTOCOL IDREF="UDS"/>
      </RESOURCE>
    </MVCI_MODULE_DESCRIPTION>""")
    cdf = _write(tmp_path / "cable.xml", """<MVCI_CABLE_DESCRIPTION>
      <DLCTYPE EID="OBD"><ID>1</ID><SHORT_NAME>OBD_16</SHORT_NAME></DLCTYPE>
      <CABLE><ID>100</ID><SHORT_NAME>OBD_CABLE</SHORT_NAME>
        <MAPPING><PIN_ON_DLC>6</PIN_ON_DLC><PIN_ON_MODULE>2</PIN_ON_MODULE></MAPPING>
        <MAPPING><PIN_ON_DLC>14</PIN_ON_DLC><PIN_ON_MODULE>3</PIN_ON_MODULE></MAPPING>
        <DLCTYPE IDREF="OBD"/>
      </CABLE>
    </MVCI_CABLE_DESCRIPTION>""")

    resource = parse_d_pdu_mdf(mdf).resources[0]
    cable = parse_d_pdu_cdf(cdf).cables[0]
    mapped = map_resource_to_dlc_pins(resource, cable)

    assert [(p.dlc_pin_number, p.pin_type_id) for p in mapped] == [(6, 2000), (14, 2001)]


def test_parse_mdf_rejects_unresolved_resource_references(tmp_path):
    mdf = _write(tmp_path / "bad.xml", """<MVCI_MODULE_DESCRIPTION>
      <RESOURCE EID="R"><ID>1</ID><SHORT_NAME>Bad</SHORT_NAME>
        <PIN_ON_MODULE><PIN_ON_MODULE>2</PIN_ON_MODULE><PINTYPE IDREF="missing"/></PIN_ON_MODULE>
        <BUSTYPE IDREF="missing"/><PROTOCOL IDREF="missing"/>
      </RESOURCE>
    </MVCI_MODULE_DESCRIPTION>""")

    try:
        parse_d_pdu_mdf(mdf)
    except DPduDescriptionError as exc:
        assert "unknown BUSTYPE" in str(exc)
    else:
        raise AssertionError("unresolved references must fail closed")


def test_description_parser_rejects_wrong_root_and_oversized_files(tmp_path):
    wrong = _write(tmp_path / "wrong.xml", "<NOT_MDF/>")
    with pytest.raises(DPduDescriptionError, match="Expected MVCI_MODULE_DESCRIPTION"):
        parse_d_pdu_mdf(wrong)
