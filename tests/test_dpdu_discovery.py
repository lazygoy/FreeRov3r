from freerov3r.hardware.dpdu_discovery import (
    DPduModuleRegistration,
    discover_d_pdu_modules,
    parse_d_pdu_root_file,
)


def _write_rdf(path, entries):
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<MVCI_PDU_API_ROOT MVCI_PART2_STANDARD_VERSION="2.2.0">'
        + entries
        + '</MVCI_PDU_API_ROOT>',
        encoding="utf-8",
    )
    return str(path)


def test_parse_rdf_extracts_module_metadata_and_file_uris(tmp_path):
    rdf = _write_rdf(
        tmp_path / "pdu_api_root.xml",
        """
        <MVCI_PDU_API>
          <SHORT_NAME>Example_D_PDU</SHORT_NAME>
          <DESCRIPTION>Example diagnostic interface</DESCRIPTION>
          <SUPPLIER_NAME>Example Supplier</SUPPLIER_NAME>
          <LIBRARY_FILE URI="file:/C:/Program%20Files/Example/pdu.dll"/>
          <MODULE_DESCRIPTION_FILE URI="file:/C:/Program%20Files/Example/mdf.xml"/>
          <CABLE_DESCRIPTION_FILE URI="file:/C:/Program%20Files/Example/cdf.xml"/>
        </MVCI_PDU_API>
        """,
    )

    modules = parse_d_pdu_root_file(rdf)

    assert modules == [
        DPduModuleRegistration(
            short_name="Example_D_PDU",
            library_file="C:/Program Files/Example/pdu.dll",
            module_description_file="C:/Program Files/Example/mdf.xml",
            cable_description_file="C:/Program Files/Example/cdf.xml",
            description="Example diagnostic interface",
            supplier_name="Example Supplier",
            root_file=rdf,
        )
    ]


def test_parse_rdf_supports_namespaced_elements_and_text_paths(tmp_path):
    rdf = tmp_path / "namespaced.xml"
    rdf.write_text(
        """<r:MVCI_PDU_API_ROOT xmlns:r="urn:example">
        <r:MVCI_PDU_API>
          <r:SHORT_NAME>Namespaced</r:SHORT_NAME>
          <r:LIBRARY_FILE>./vendor.dll</r:LIBRARY_FILE>
          <r:MODULE_DESCRIPTION_PATH>./mdf.xml</r:MODULE_DESCRIPTION_PATH>
          <r:CABLE_DESCRIPTION_PATH>./cdf.xml</r:CABLE_DESCRIPTION_PATH>
        </r:MVCI_PDU_API>
        </r:MVCI_PDU_API_ROOT>""",
        encoding="utf-8",
    )

    modules = parse_d_pdu_root_file(str(rdf))

    assert len(modules) == 1
    assert modules[0].short_name == "Namespaced"
    assert modules[0].library_file == "./vendor.dll"
    assert modules[0].module_description_file == str(tmp_path / "mdf.xml")
    assert modules[0].cable_description_file == str(tmp_path / "cdf.xml")


def test_parse_rdf_ignores_entries_missing_required_identity_or_library(tmp_path):
    rdf = _write_rdf(
        tmp_path / "incomplete.xml",
        """
        <MVCI_PDU_API>
          <SHORT_NAME>Missing library</SHORT_NAME>
        </MVCI_PDU_API>
        <MVCI_PDU_API>
          <LIBRARY_FILE URI="vendor.dll"/>
        </MVCI_PDU_API>
        """,
    )

    assert parse_d_pdu_root_file(rdf) == []


def test_parse_rdf_returns_empty_for_missing_or_malformed_files(tmp_path):
    missing = tmp_path / "missing.xml"
    malformed = tmp_path / "broken.xml"
    malformed.write_text("<MVCI_PDU_API_ROOT><", encoding="utf-8")

    assert parse_d_pdu_root_file(str(missing)) == []
    assert parse_d_pdu_root_file(str(malformed)) == []


def test_discovery_deduplicates_roots_and_module_entries(tmp_path):
    rdf = _write_rdf(
        tmp_path / "root.xml",
        """
        <MVCI_PDU_API>
          <SHORT_NAME>Example</SHORT_NAME>
          <LIBRARY_FILE URI="file:/opt/example/pdu.so"/>
        </MVCI_PDU_API>
        """,
    )

    modules = discover_d_pdu_modules(
        [rdf, rdf],
        root_file_reader=lambda: (_ for _ in ()).throw(
            AssertionError("explicit root_files must bypass registry discovery")
        ),
    )

    assert len(modules) == 1
    assert modules[0].short_name == "Example"


def test_discovery_uses_injected_root_file_reader(tmp_path):
    rdf = _write_rdf(
        tmp_path / "reader.xml",
        """
        <MVCI_PDU_API>
          <SHORT_NAME>ReaderModule</SHORT_NAME>
          <LIBRARY_FILE URI="reader.dll"/>
        </MVCI_PDU_API>
        """,
    )

    modules = discover_d_pdu_modules(root_file_reader=lambda: [rdf])

    assert [module.short_name for module in modules] == ["ReaderModule"]


def test_discovery_does_not_load_any_library(tmp_path):
    rdf = _write_rdf(
        tmp_path / "passive.xml",
        """
        <MVCI_PDU_API>
          <SHORT_NAME>PassiveOnly</SHORT_NAME>
          <LIBRARY_FILE URI="this-file-does-not-exist.dll"/>
        </MVCI_PDU_API>
        """,
    )

    modules = discover_d_pdu_modules([rdf])

    assert len(modules) == 1
    assert modules[0].library_file == "this-file-does-not-exist.dll"

def test_rdf_resolves_relative_mdf_and_cdf_paths_from_root_directory(tmp_path):
    (tmp_path / "mdf.xml").write_text("<MVCI_MODULE_DESCRIPTION/>", encoding="utf-8")
    (tmp_path / "cdf.xml").write_text("<MVCI_CABLE_DESCRIPTION/>", encoding="utf-8")
    rdf = _write_rdf(
        tmp_path / "root.xml",
        """
        <MVCI_PDU_API>
          <SHORT_NAME>RelativePaths</SHORT_NAME>
          <LIBRARY_FILE URI="file:/opt/vendor/pdu.dll"/>
          <MODULE_DESCRIPTION_FILE URI="mdf.xml"/>
          <CABLE_DESCRIPTION_FILE URI="cdf.xml"/>
        </MVCI_PDU_API>
        """,
    )

    registration = parse_d_pdu_root_file(rdf)[0]

    assert registration.module_description_file == str(tmp_path / "mdf.xml")
    assert registration.cable_description_file == str(tmp_path / "cdf.xml")
