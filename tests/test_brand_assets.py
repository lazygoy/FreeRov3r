from pathlib import Path
import xml.etree.ElementTree as ET


ASSET_DIR = Path(__file__).parents[1] / "src" / "freerov3r" / "assets"


def test_brand_artwork_assets_are_valid_svg():
    for name in ("brand_badge.svg", "brand_banner.svg", "brand_splash.svg"):
        path = ASSET_DIR / name
        assert path.is_file(), f"Missing brand asset: {name}"
        root = ET.parse(path).getroot()
        assert root.tag.endswith("svg"), f"Invalid SVG root in {name}"
        assert root.attrib.get("viewBox"), f"Missing viewBox in {name}"
