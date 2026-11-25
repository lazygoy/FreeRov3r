from pathlib import Path
import xml.etree.ElementTree as ET

from PySide6.QtWidgets import QApplication

from freerov3r.asset_loader import load_asset_pixmap


ASSET_DIR = Path(__file__).parents[1] / "src" / "freerov3r" / "assets"


def test_brand_artwork_assets_are_valid_svg():
    for name in ("brand_badge.svg", "brand_banner.svg", "brand_splash.svg"):
        path = ASSET_DIR / name
        assert path.is_file(), f"Missing brand asset: {name}"
        root = ET.parse(path).getroot()
        assert root.tag.endswith("svg"), f"Invalid SVG root in {name}"
        assert root.attrib.get("viewBox"), f"Missing viewBox in {name}"


def test_brand_assets_render_to_pixmaps():
    app = QApplication.instance() or QApplication([])
    for name in ("brand_badge.svg", "brand_banner.svg", "brand_splash.svg"):
        pixmap = load_asset_pixmap(name)
        assert not pixmap.isNull(), f"Could not render brand asset: {name}"
        assert pixmap.width() > 0 and pixmap.height() > 0
