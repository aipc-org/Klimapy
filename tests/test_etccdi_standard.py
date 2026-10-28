"""Definition-based regressions for standard ETCCDI behavior."""
from unittest import TestCase
import numpy as np
import xarray as xr
from klimapy import ETCCDI as api
from klimapy.ETCCDI import ETCCDI as et


def daily(values, start='2001-01-01', name='pr', calendar=None):
    options = {'calendar': calendar, 'use_cftime': True} if calendar else {}
    return xr.DataArray(np.asarray(values, dtype=float), dims='time',
                        coords={'time': xr.date_range(start, periods=len(values), **options)},
                        name=name, attrs={'units': 'mm/day' if name == 'pr' else 'degC'})


class StandardTests(TestCase):
    def test_wet_day_sum_and_intensity(self):
        pr = daily([10] + [0.5] * 364)
        self.assertEqual(et.PRCPTOT(pr).item(), 10)
        self.assertEqual(et.SDII(pr).item(), 10)
        pr[:] = 0.5
        self.assertEqual(et.PRCPTOT(pr).item(), 0)
        self.assertTrue(et.SDII(pr).isnull().all())

    def test_custom_threshold_and_aliases(self):
        pr = daily([7, 7.5, 8] + [0] * 362)
        self.assertEqual(api.Rnnmm(pr, threshold=7.5).item(), 2)
        self.assertEqual(api.Rnnmm(pr, threshold=7.5).name, 'Rnnmm')
        for threshold in (-1, np.nan, np.inf, True):
            with self.assertRaises(ValueError):
                api.Rnnmm(pr, threshold=threshold)
        self.assertIs(api.R10mm, api.R10mm_days)
        self.assertIs(api.R95p, api.R95mm_precipitation)
        self.assertIs(api.R99pTOT, api.R99mm_precipitation)
        self.assertIs(api.RXdday, api.RXnday)

    def test_cross_year_window_and_monthly_output(self):
        pr = daily(np.zeros(730))
        pr.loc[{'time': slice('2001-12-30', '2002-01-03')}] = 10
        result = api.RX5DAY(pr)
        self.assertEqual(result.name, 'RX5DAY')
        self.assertEqual(result.sel(year=2001).item(), 20)
        self.assertEqual(result.sel(year=2002).item(), 50)
        monthly = api.Rx5day(pr, freq='MS')
        self.assertEqual(monthly.sel(time='2002-01-01').item(), 50)
        self.assertEqual(monthly.sizes['time'], 24)
        self.assertEqual(monthly.attrs['units'], 'mm')
        pr.loc[{'time': '2002-01-01'}] = np.nan
        self.assertEqual(api.RX5DAY(pr).sel(year=2002).item(), 20)
        with self.assertRaises(ValueError):
            api.RXnday(pr, window=0)
        with self.assertRaises(ValueError):
            api.RX1DAY(pr, freq='QS')

    def test_monthly_coverage_and_native_calendar(self):
        pr = daily(np.ones(360), calendar='360_day')
        result = api.RXnday(pr, window=3, freq='MS')
        self.assertEqual(result.sizes['time'], 12)
        np.testing.assert_allclose(result, 3)
        pr[:4] = np.nan
        self.assertTrue(api.RX1DAY(pr, freq='MS').isel(time=0).isnull())
        self.assertTrue(api.RXnday(pr * np.nan).isnull().all())

    def test_batch_per_index_options_and_tiling(self):
        pr = daily([10] + [0.5] * 364).expand_dims(lat=[30], lon=[100])
        settings = {'Rnnmm': {'threshold': 9.5}, 'Rx5day': {'freq': 'MS'}}
        result = api.compute_indices(pr, list(settings), index_options=settings, spatial_chunk_size=1)
        self.assertEqual(result.Rnnmm.item(), 1)
        self.assertEqual(result.Rx5day.sizes['time'], 12)
        for options in ({'SDII': {}}, {'Rnnmm': {'pr': pr}}, {'Rnnmm': {'thresholdd': 3}}):
            with self.assertRaises(ValueError):
                api.compute_indices(pr, ['Rnnmm'], index_options=options)

    def test_bootstrap_replacement_and_out_of_base_period(self):
        tx = daily(np.repeat([10, 30, 40], 365), name='tx')
        corrected = api.TX90p(tx, baseline_years=(2001, 2002))
        plain = api.TX90p(tx, baseline_years=(2001, 2002), bootstrap=False)
        np.testing.assert_allclose(corrected, [0, 100, 100])
        np.testing.assert_allclose(plain, [0, 0, 100])
        self.assertIn('replacement', corrected.attrs['bootstrap'])
        with self.assertRaisesRegex(ValueError, 'at least two'):
            api.TX90p(tx, baseline_years=(2001, 2001))

    def test_bootstrap_averages_indices_not_thresholds(self):
        # Two donor replacements produce 100% and 0%; averaging the thresholds
        # would instead compare 10 > 10 and incorrectly return 0%.
        tx = daily(np.repeat([0, 10, 20], 365), name='tx')
        result = et._bootstrap_temperature_percentage(et.check_temperature_data(tx), (2001, 2003), 50, True)
        np.testing.assert_allclose(result, [0, 50, 100])

    def test_bootstrap_missing_data_and_360_day(self):
        tx = daily(np.repeat([10, 30], 360), name='tx', calendar='360_day')
        tx[360:370] = np.nan
        result = api.TX90p(tx, baseline_years=(2001, 2002))
        np.testing.assert_allclose(result, [0, 100])
        tx[360:] = np.nan
        self.assertTrue(api.TX90p(tx, baseline_years=(2001, 2002)).isnull().all())
