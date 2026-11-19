"""Direct float32 input must preserve float64 accumulator semantics."""
import ctypes as ct
import unittest
import numpy as np
from klimapy._backends.rust import climate_accumulate, climate_mean, _library

class Float32AccumulatorTests(unittest.TestCase):
    def test_layouts_groups_missing_and_multiple_blocks(self):
        base=np.random.default_rng(19).normal(size=(17,5,7)).astype('float32')
        base[::3,1,2]=np.nan;base[:,0,0]=np.nan
        base[0,2,3]=np.inf;base[1,2,3]=-np.inf
        for values in [base,np.asfortranarray(base),base[:,:,::-1],base.astype('>f4')]:
            labels=np.arange(17,dtype=np.intp)%3;labels[4]=-1
            sums=np.zeros((3,*values.shape[1:]),dtype='float64');counts=np.zeros(sums.shape,dtype='int32')
            for start,end in [(0,4),(4,11),(11,17)]:
                climate_accumulate(values[start:end],labels[start:end],sums,counts)
            expected_sums=np.zeros_like(sums);expected_counts=np.zeros_like(counts)
            for t,label in enumerate(labels):
                if label<0:continue
                for y in range(values.shape[1]):
                    for x in range(values.shape[2]):
                        value=float(values[t,y,x])
                        if np.isfinite(value):
                            expected_sums[label,y,x]+=value;expected_counts[label,y,x]+=1
            np.testing.assert_array_equal(sums,expected_sums)
            np.testing.assert_array_equal(counts,expected_counts)
            expected=np.divide(expected_sums,expected_counts,out=np.full_like(sums,np.nan),where=expected_counts>0)
            np.testing.assert_array_equal(climate_mean(sums,counts),expected)

    def test_fast_symbol_and_no_float64_cube(self):
        from unittest.mock import patch
        import klimapy._backends.rust as backend
        self.assertTrue(hasattr(_library(),'climate_accumulate_f32'))
        # A contiguous float32 block must bypass the float64 cube adapter.
        sums=np.zeros((1,2,3));counts=np.zeros(sums.shape,dtype='int32')
        with patch.object(backend,'_cube',side_effect=AssertionError('conversion')):
            climate_accumulate(np.ones((4,2,3),dtype='float32'),np.zeros(4,dtype=np.intp),sums,counts)
        np.testing.assert_array_equal(sums,4)
        np.testing.assert_array_equal(counts,4)

    def test_unaligned_float32_and_integer_compatibility(self):
        raw=bytearray(4*24+1)
        unaligned=np.ndarray((4,2,3),dtype='float32',buffer=raw,offset=1);unaligned[:]=2
        for values in [unaligned,np.full((4,2,3),2,dtype='int16'),np.full((4,2,3),2.)]:
            sums=np.zeros((1,2,3));counts=np.zeros(sums.shape,dtype='int32')
            climate_accumulate(values,np.zeros(4,dtype=np.intp),sums,counts)
            np.testing.assert_array_equal(sums,8)

    def test_invalid_group_and_count_overflow(self):
        values=np.ones((1,2,3),dtype='float32')
        sums=np.zeros((1,2,3));counts=np.zeros(sums.shape,dtype='int32')
        with self.assertRaises((ValueError,RuntimeError)):
            climate_accumulate(values,np.array([1],dtype=np.intp),sums,counts)
        np.testing.assert_array_equal(sums,0)
        counts[:]=np.iinfo(np.int32).max
        with self.assertRaises((ValueError,RuntimeError)):
            climate_accumulate(values,np.array([0],dtype=np.intp),sums,counts)
        with self.assertRaises(ValueError):
            climate_accumulate(values,np.zeros(2,dtype=np.intp),sums,counts)
        with self.assertRaises(ValueError):
            climate_accumulate(values,np.zeros(1,dtype=np.intp),sums.astype('float32'),counts)
