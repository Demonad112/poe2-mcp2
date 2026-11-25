"""Path of Building export functionality"""

import base64
import logging
import zlib
from typing import Any, Dict

from .xml_generator import PoBXMLGenerator

logger = logging.getLogger(__name__)


class PoBExporter:
    """Export builds to Path of Building 2 share-code format"""

    async def export_build(self, character_data: Dict[str, Any]) -> str:
        """
        Export character to a PoB2 share code.

        Encoding matches PoB's ImportTab: XML -> zlib (level 9) -> base64
        with ``+``/``/`` swapped for ``-``/``_`` (padding kept).

        Args:
            character_data: Character data to export

        Returns:
            PoB share code
        """
        try:
            xml_str = PoBXMLGenerator().generate(character_data)
            compressed = zlib.compress(xml_str.encode("utf-8"), 9)
            encoded = base64.b64encode(compressed).decode("ascii")
            return encoded.replace("+", "-").replace("/", "_")
        except Exception as e:
            logger.error(f"PoB export failed: {e}")
            raise ValueError(f"Export failed: {str(e)}")
