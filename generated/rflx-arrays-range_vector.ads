pragma SPARK_Mode;
with RFLX.Scalar_Sequence;
with RFLX.Arrays;

package RFLX.Arrays.Range_Vector is new Scalar_Sequence (Range_Integer, Range_Integer_Base, Convert, Valid, Convert);