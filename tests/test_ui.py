import re
from pathlib import Path
import unittest


class UiContractTests(unittest.TestCase):
    def test_script_references_existing_elements(self):
        root = Path(__file__).resolve().parents[1] / 'static'
        html = (root / 'index.html').read_text(encoding='utf-8')
        script = (root / 'app.js').read_text(encoding='utf-8')
        ids = set(re.findall(r'id="([^"]+)"', html))
        references = set(re.findall(r"\$\('([^']+)'\)", script))
        self.assertFalse(references - ids, 'Missing HTML IDs: ' + ', '.join(sorted(references - ids)))


if __name__ == '__main__': unittest.main()
