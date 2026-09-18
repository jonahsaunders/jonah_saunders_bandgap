import tempfile
from pathlib import Path
import unittest

import numpy as np
import run_trim as t


class TrimBenchTests(unittest.TestCase):
    def test_all_bit_codes(self):
        for code in range(128):
            self.assertEqual(sum(v << i for i,v in enumerate(t.bits(code))),code)
            self.assertTrue(all(v in (0,1) for v in t.bits(code)))
        self.assertEqual(t.bits(70),[0,1,1,0,0,0,1])

    def test_invalid_codes(self):
        for code in (-1,128):
            with self.assertRaises(ValueError): t.bits(code)

    def test_digital_drive_stays_3p3(self):
        for v in (3.3,5):
            deck,_=t.startup_deck(v,70)
            self.assertIn('11u 3.3 6m 3.3',deck)
            self.assertIn('EBIT1 b1 0 dvdd 0 1',deck)
            self.assertIn('EBIT0 b0 0 dvdd 0 0',deck)

    def test_error_detector(self):
        self.assertIsNotNone(t.ERRORS.search('doAnalyses: TRAN: Timestep too small'))
        self.assertIsNotNone(t.ERRORS.search('Error: no such vector vr'))
        self.assertIsNone(t.ERRORS.search('Dynamic gmin stepping completed'))

    def valid_table(self):
        return np.array([[code,v,3.3,1.194,.708,25e-6,1e-10,0,0,0,0,1e-7,1e-6,1e-6]
                         for v in (3.3,5) for code in range(128)],dtype=float)

    def parse(self,data):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'table.txt'
            np.savetxt(p,data,header=' '.join(t.FIELDS),comments='')
            return t.read_sweep(p)

    def test_complete_sweep(self):
        rows=self.parse(self.valid_table())
        self.assertEqual(len(rows),256)
        self.assertTrue(all(r['self_sustaining_op'] for r in rows))

    def test_incomplete_sweep(self):
        with self.assertRaises(RuntimeError): self.parse(self.valid_table()[:-1])

    def test_duplicate_code(self):
        a=self.valid_table();a[1]=a[0]
        with self.assertRaises(RuntimeError): self.parse(a)

    def test_nonfinite_sweep(self):
        a=self.valid_table();a[0,3]=np.nan
        with self.assertRaises(RuntimeError): self.parse(a)

    def test_assistance_not_mistaken_for_pass(self):
        a=self.valid_table();a[0,8]=2e-9
        self.assertFalse(self.parse(a)[0]['self_sustaining_op'])

    def test_full_precision_writer(self):
        control=t.sweep_control(Path('/tmp/unused_trim_table.txt'))
        self.assertIn('wrdata ',control)
        self.assertIn('setscale code_value',control)
        self.assertNotIn('echo $code',control)


if __name__=='__main__':
    unittest.main()
