"""Checks Excel namespace compatibility and preservation of the original template."""
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from lxml import etree
from quality import legacy

MC = '{http://schemas.openxmlformats.org/markup-compatibility/2006}Ignorable'
TEMPLATE = Path(__file__).parent / 'quality/templates/report_template.xlsm'

class XlsmExportTests(unittest.TestCase):
    def test_template_export_preserves_excel_namespaces_and_parts(self):
        job = dict(order_number='TEST', brief_description='Kontrola', norm_mode='ct', norm_ct_seconds=10, errors=[])
        for warning in (False, True):
            with self.subTest(warning=warning), tempfile.TemporaryDirectory() as folder:
                counter = iter(range(10))
                def tempdir(**kwargs):
                    path = Path(folder) / str(next(counter))
                    path.mkdir()
                    return str(path)
                record = dict(record_date='2026-09-17', shift='R', part_snapshot_obj={'item_number':'00123'},
                    error_counts_obj={}, checked_items=28, ok_items=28, nok_items=0,
                    reworked_ok=0, reworked_nok=0, user_id=1, display_name='Test', username='test',
                    work_time_seconds=280, norm_outside=warning, delivery_note='000456')
                with patch.object(legacy, 'TEMPLATE_PATH', str(TEMPLATE)), patch.object(legacy.tempfile, 'mkdtemp', tempdir):
                    output = legacy.daily_template_export(job, [record])
                with zipfile.ZipFile(TEMPLATE) as source, zipfile.ZipFile(output) as result:
                    self.assertEqual(set(source.namelist()), set(result.namelist()))
                    for name in source.namelist():
                        if name not in ('xl/worksheets/sheet1.xml', 'xl/styles.xml'):
                            self.assertEqual(source.read(name), result.read(name), name)
                        if name.endswith('.xml'):
                            root = etree.fromstring(result.read(name))
                            for node in root.iter():
                                for prefix in node.get(MC, '').split():
                                    self.assertIn(prefix, node.nsmap, (name, prefix))
                    sheet = etree.fromstring(result.read('xl/worksheets/sheet1.xml'))
                    ns = {'m': legacy.NS_MAIN}
                    self.assertEqual(sheet.xpath('string(//m:c[@r="D8"]/m:is/m:t)', namespaces=ns), '000456')
                    self.assertEqual(sheet.xpath('string(//m:c[@r="E8"]/m:v)', namespaces=ns), '28')
                    self.assertEqual(sheet.nsmap, etree.fromstring(source.read('xl/worksheets/sheet1.xml')).nsmap)

if __name__ == '__main__':
    unittest.main()
