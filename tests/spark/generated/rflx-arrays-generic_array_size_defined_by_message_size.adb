pragma Style_Checks ("N3aAbcdefhiIklnOprStux");

package body RFLX.Arrays.Generic_Array_Size_Defined_By_Message_Size with
  SPARK_Mode
is

   procedure Initialize (Ctx : out Context; Buffer : in out Types.Bytes_Ptr) is
   begin
      Initialize (Ctx, Buffer, Types.First_Bit_Index (Buffer'First), Types.Last_Bit_Index (Buffer'Last));
   end Initialize;

   procedure Initialize (Ctx : out Context; Buffer : in out Types.Bytes_Ptr; First, Last : Types.Bit_Index) is
      Buffer_First : constant Types.Index := Buffer'First;
      Buffer_Last : constant Types.Index := Buffer'Last;
   begin
      Ctx := (Buffer_First, Buffer_Last, First, Last, First, Buffer, (F_Header => (State => S_Invalid, Predecessor => F_Initial), others => (State => S_Invalid, Predecessor => F_Final)));
      Buffer := null;
   end Initialize;

   function Initialized (Ctx : Context) return Boolean is
     (Valid_Next (Ctx, F_Header)
      and then Available_Space (Ctx, F_Header) = Ctx.Last - Ctx.First + 1
      and then Invalid (Ctx, F_Header)
      and then Invalid (Ctx, F_Vector));

   procedure Take_Buffer (Ctx : in out Context; Buffer : out Types.Bytes_Ptr) is
   begin
      Buffer := Ctx.Buffer;
      Ctx.Buffer := null;
   end Take_Buffer;

   function Has_Buffer (Ctx : Context) return Boolean is
     (Ctx.Buffer /= null);

   function Message_Last (Ctx : Context) return Types.Bit_Index is
     (Ctx.Message_Last);

   function Path_Condition (Ctx : Context; Fld : Field) return Boolean is
     ((case Ctx.Cursors (Fld).Predecessor is
          when F_Initial =>
             (case Fld is
                 when F_Header =>
                    True,
                 when others =>
                    False),
          when F_Header =>
             (case Fld is
                 when F_Vector =>
                    True,
                 when others =>
                    False),
          when F_Vector | F_Final =>
             False));

   function Field_Condition (Ctx : Context; Val : Field_Dependent_Value) return Boolean is
     ((case Val.Fld is
          when F_Initial | F_Header | F_Vector =>
             True,
          when F_Final =>
             False));

   function Field_Size (Ctx : Context; Fld : Field) return Types.Bit_Length is
     ((case Ctx.Cursors (Fld).Predecessor is
          when F_Initial =>
             (case Fld is
                 when F_Header =>
                    RFLX.Arrays.Enumeration_Base'Size,
                 when others =>
                    Types.Unreachable_Bit_Length),
          when F_Header =>
             (case Fld is
                 when F_Vector =>
                    Ctx.Last - Ctx.First + 1 - Types.Bit_Length (Ctx.Cursors (F_Header).Last - Ctx.Cursors (F_Header).First + 1),
                 when others =>
                    Types.Unreachable_Bit_Length),
          when F_Vector | F_Final =>
             0));

   function Field_First (Ctx : Context; Fld : Field) return Types.Bit_Index is
     ((case Fld is
          when F_Header =>
             Ctx.First,
          when F_Vector =>
             (if
                 Ctx.Cursors (Fld).Predecessor = F_Header
              then
                 Ctx.Cursors (Ctx.Cursors (Fld).Predecessor).Last + 1
              else
                 Types.Unreachable_Bit_Length)));

   function Field_Last (Ctx : Context; Fld : Field) return Types.Bit_Index is
     (Field_First (Ctx, Fld) + Field_Size (Ctx, Fld) - 1);

   function Predecessor (Ctx : Context; Fld : Virtual_Field) return Virtual_Field is
     ((case Fld is
          when F_Initial =>
             F_Initial,
          when others =>
             Ctx.Cursors (Fld).Predecessor));

   function Successor (Ctx : Context; Fld : Field) return Virtual_Field is
     ((case Fld is
          when F_Header =>
             F_Vector,
          when F_Vector =>
             F_Final))
    with
     Pre =>
       Has_Buffer (Ctx)
       and Structural_Valid (Ctx, Fld)
       and Valid_Predecessor (Ctx, Fld);

   function Valid_Predecessor (Ctx : Context; Fld : Virtual_Field) return Boolean is
     ((case Fld is
          when F_Initial =>
             True,
          when F_Header =>
             Ctx.Cursors (Fld).Predecessor = F_Initial,
          when F_Vector =>
             (Valid (Ctx.Cursors (F_Header))
              and Ctx.Cursors (Fld).Predecessor = F_Header),
          when F_Final =>
             (Structural_Valid (Ctx.Cursors (F_Vector))
              and Ctx.Cursors (Fld).Predecessor = F_Vector)));

   function Invalid_Successor (Ctx : Context; Fld : Field) return Boolean is
     ((case Fld is
          when F_Header =>
             Invalid (Ctx.Cursors (F_Vector)),
          when F_Vector =>
             True));

   function Valid_Next (Ctx : Context; Fld : Field) return Boolean is
     (Valid_Predecessor (Ctx, Fld)
      and then Path_Condition (Ctx, Fld));

   function Available_Space (Ctx : Context; Fld : Field) return Types.Bit_Length is
     (Ctx.Last - Field_First (Ctx, Fld) + 1);

   function Sufficient_Buffer_Length (Ctx : Context; Fld : Field) return Boolean is
     (Ctx.Buffer /= null
      and Ctx.First <= Types.Bit_Index'Last / 2
      and Field_First (Ctx, Fld) <= Types.Bit_Index'Last / 2
      and Field_Size (Ctx, Fld) >= 0
      and Field_Size (Ctx, Fld) <= Types.Bit_Length'Last / 2
      and Field_First (Ctx, Fld) + Field_Size (Ctx, Fld) <= Types.Bit_Length'Last / 2
      and Ctx.First <= Field_First (Ctx, Fld)
      and Ctx.Last >= Field_Last (Ctx, Fld))
    with
     Pre =>
       Has_Buffer (Ctx)
       and Valid_Next (Ctx, Fld);

   function Equal (Ctx : Context; Fld : Field; Data : Types.Bytes) return Boolean is
     (Sufficient_Buffer_Length (Ctx, Fld)
      and then (case Fld is
                   when F_Vector =>
                      Ctx.Buffer.all (Types.Byte_Index (Field_First (Ctx, Fld)) .. Types.Byte_Index (Field_Last (Ctx, Fld))) = Data,
                   when others =>
                      False));

   procedure Reset_Dependent_Fields (Ctx : in out Context; Fld : Field) with
     Pre =>
       Valid_Next (Ctx, Fld),
     Post =>
       Valid_Next (Ctx, Fld)
       and Invalid (Ctx.Cursors (Fld))
       and Invalid_Successor (Ctx, Fld)
       and Ctx.Buffer_First = Ctx.Buffer_First'Old
       and Ctx.Buffer_Last = Ctx.Buffer_Last'Old
       and Ctx.First = Ctx.First'Old
       and Ctx.Last = Ctx.Last'Old
       and Ctx.Cursors (Fld).Predecessor = Ctx.Cursors (Fld).Predecessor'Old
       and Has_Buffer (Ctx) = Has_Buffer (Ctx)'Old
       and Field_First (Ctx, Fld) = Field_First (Ctx, Fld)'Old
       and Field_Size (Ctx, Fld) = Field_Size (Ctx, Fld)'Old
       and (case Fld is
               when F_Header =>
                  Invalid (Ctx, F_Header)
                  and Invalid (Ctx, F_Vector),
               when F_Vector =>
                  Ctx.Cursors (F_Header) = Ctx.Cursors (F_Header)'Old
                  and Invalid (Ctx, F_Vector))
   is
      First : constant Types.Bit_Length := Field_First (Ctx, Fld) with
        Ghost;
      Size : constant Types.Bit_Length := Field_Size (Ctx, Fld) with
        Ghost;
   begin
      pragma Assert (Field_First (Ctx, Fld) = First
                     and Field_Size (Ctx, Fld) = Size);
      case Fld is
         when F_Header =>
            Ctx.Cursors (F_Vector) := (S_Invalid, F_Final);
            Ctx.Cursors (F_Header) := (S_Invalid, Ctx.Cursors (F_Header).Predecessor);
            pragma Assert (Field_First (Ctx, Fld) = First
                           and Field_Size (Ctx, Fld) = Size);
         when F_Vector =>
            Ctx.Cursors (F_Vector) := (S_Invalid, Ctx.Cursors (F_Vector).Predecessor);
            pragma Assert (Field_First (Ctx, Fld) = First
                           and Field_Size (Ctx, Fld) = Size);
      end case;
   end Reset_Dependent_Fields;

   function Composite_Field (Fld : Field) return Boolean is
     ((case Fld is
          when F_Header =>
             False,
          when F_Vector =>
             True));

   function Get_Field_Value (Ctx : Context; Fld : Field) return Field_Dependent_Value with
     Pre =>
       Has_Buffer (Ctx)
       and then Valid_Next (Ctx, Fld)
       and then Sufficient_Buffer_Length (Ctx, Fld),
     Post =>
       Get_Field_Value'Result.Fld = Fld
   is
      First : constant Types.Bit_Index := Field_First (Ctx, Fld);
      Last : constant Types.Bit_Index := Field_Last (Ctx, Fld);
      function Buffer_First return Types.Index is
        (Types.Byte_Index (First));
      function Buffer_Last return Types.Index is
        (Types.Byte_Index (Last));
      function Offset return Types.Offset is
        (Types.Offset ((8 - Last mod 8) mod 8));
      function Extract is new Types.Extract (RFLX.Arrays.Enumeration_Base);
   begin
      return ((case Fld is
                  when F_Header =>
                     (Fld => F_Header, Header_Value => Extract (Ctx.Buffer.all (Buffer_First .. Buffer_Last), Offset)),
                  when F_Vector =>
                     (Fld => F_Vector)));
   end Get_Field_Value;

   procedure Verify (Ctx : in out Context; Fld : Field) is
      Value : Field_Dependent_Value;
   begin
      if
        Has_Buffer (Ctx)
        and then Invalid (Ctx.Cursors (Fld))
        and then Valid_Predecessor (Ctx, Fld)
        and then Path_Condition (Ctx, Fld)
      then
         if Sufficient_Buffer_Length (Ctx, Fld) then
            Value := Get_Field_Value (Ctx, Fld);
            if
              Valid_Value (Value)
              and Field_Condition (Ctx, Value)
            then
               Ctx.Message_Last := Field_Last (Ctx, Fld);
               if Composite_Field (Fld) then
                  Ctx.Cursors (Fld) := (State => S_Structural_Valid, First => Field_First (Ctx, Fld), Last => Field_Last (Ctx, Fld), Value => Value, Predecessor => Ctx.Cursors (Fld).Predecessor);
               else
                  Ctx.Cursors (Fld) := (State => S_Valid, First => Field_First (Ctx, Fld), Last => Field_Last (Ctx, Fld), Value => Value, Predecessor => Ctx.Cursors (Fld).Predecessor);
               end if;
               pragma Assert ((if
                                  Structural_Valid (Ctx.Cursors (F_Header))
                               then
                                  Ctx.Cursors (F_Header).Last - Ctx.Cursors (F_Header).First + 1 = RFLX.Arrays.Enumeration_Base'Size
                                  and then Ctx.Cursors (F_Header).Predecessor = F_Initial
                                  and then Ctx.Cursors (F_Header).First = Ctx.First
                                  and then (if
                                               Structural_Valid (Ctx.Cursors (F_Vector))
                                            then
                                               Ctx.Cursors (F_Vector).Last - Ctx.Cursors (F_Vector).First + 1 = Ctx.Last - Ctx.First + 1 - Types.Bit_Length (Ctx.Cursors (F_Header).Last - Ctx.Cursors (F_Header).First + 1)
                                               and then Ctx.Cursors (F_Vector).Predecessor = F_Header
                                               and then Ctx.Cursors (F_Vector).First = Ctx.Cursors (F_Header).Last + 1)));
               if Fld = F_Header then
                  Ctx.Cursors (Successor (Ctx, Fld)) := (State => S_Invalid, Predecessor => Fld);
               elsif Fld = F_Vector then
                  Ctx.Cursors (Successor (Ctx, Fld)) := (State => S_Invalid, Predecessor => Fld);
               end if;
            else
               Ctx.Cursors (Fld) := (State => S_Invalid, Predecessor => F_Final);
            end if;
         else
            Ctx.Cursors (Fld) := (State => S_Incomplete, Predecessor => F_Final);
         end if;
      end if;
   end Verify;

   procedure Verify_Message (Ctx : in out Context) is
   begin
      Verify (Ctx, F_Header);
      Verify (Ctx, F_Vector);
   end Verify_Message;

   function Present (Ctx : Context; Fld : Field) return Boolean is
     (Structural_Valid (Ctx.Cursors (Fld))
      and then Ctx.Cursors (Fld).First < Ctx.Cursors (Fld).Last + 1);

   function Structural_Valid (Ctx : Context; Fld : Field) return Boolean is
     ((Ctx.Cursors (Fld).State = S_Valid
       or Ctx.Cursors (Fld).State = S_Structural_Valid));

   function Valid (Ctx : Context; Fld : Field) return Boolean is
     (Ctx.Cursors (Fld).State = S_Valid
      and then Ctx.Cursors (Fld).First < Ctx.Cursors (Fld).Last + 1);

   function Incomplete (Ctx : Context; Fld : Field) return Boolean is
     (Ctx.Cursors (Fld).State = S_Incomplete);

   function Invalid (Ctx : Context; Fld : Field) return Boolean is
     (Ctx.Cursors (Fld).State = S_Invalid
      or Ctx.Cursors (Fld).State = S_Incomplete);

   function Structural_Valid_Message (Ctx : Context) return Boolean is
     (Valid (Ctx, F_Header)
      and then Structural_Valid (Ctx, F_Vector));

   function Valid_Message (Ctx : Context) return Boolean is
     (Valid (Ctx, F_Header)
      and then Valid (Ctx, F_Vector));

   function Incomplete_Message (Ctx : Context) return Boolean is
     (Incomplete (Ctx, F_Header)
      or Incomplete (Ctx, F_Vector));

   function Get_Header (Ctx : Context) return RFLX.Arrays.Enumeration is
     (To_Actual (Ctx.Cursors (F_Header).Value.Header_Value));

   procedure Get_Vector (Ctx : Context) is
      First : constant Types.Index := Types.Byte_Index (Ctx.Cursors (F_Vector).First);
      Last : constant Types.Index := Types.Byte_Index (Ctx.Cursors (F_Vector).Last);
   begin
      Process_Vector (Ctx.Buffer.all (First .. Last));
   end Get_Vector;

   procedure Set_Field_Value (Ctx : in out Context; Val : Field_Dependent_Value; Fst, Lst : out Types.Bit_Index) with
     Pre =>
       not Ctx'Constrained
       and then Has_Buffer (Ctx)
       and then Val.Fld in Field'Range
       and then Valid_Next (Ctx, Val.Fld)
       and then Available_Space (Ctx, Val.Fld) >= Field_Size (Ctx, Val.Fld)
       and then (for all F in Field'Range =>
                    (if
                        Structural_Valid (Ctx.Cursors (F))
                     then
                        Ctx.Cursors (F).Last <= Field_Last (Ctx, Val.Fld))),
     Post =>
       Has_Buffer (Ctx)
       and Fst = Field_First (Ctx, Val.Fld)
       and Lst = Field_Last (Ctx, Val.Fld)
       and Fst >= Ctx.First
       and Fst <= Lst + 1
       and Lst <= Ctx.Last
       and (for all F in Field'Range =>
               (if
                   Structural_Valid (Ctx.Cursors (F))
                then
                   Ctx.Cursors (F).Last <= Lst))
       and Ctx.Buffer_First = Ctx.Buffer_First'Old
       and Ctx.Buffer_Last = Ctx.Buffer_Last'Old
       and Ctx.First = Ctx.First'Old
       and Ctx.Last = Ctx.Last'Old
       and Ctx.Cursors = Ctx.Cursors'Old
   is
      First : constant Types.Bit_Index := Field_First (Ctx, Val.Fld);
      Last : constant Types.Bit_Index := Field_Last (Ctx, Val.Fld);
      function Buffer_First return Types.Index is
        (Types.Byte_Index (First));
      function Buffer_Last return Types.Index is
        (Types.Byte_Index (Last));
      function Offset return Types.Offset is
        (Types.Offset ((8 - Last mod 8) mod 8));
      procedure Insert is new Types.Insert (RFLX.Arrays.Enumeration_Base);
   begin
      Fst := First;
      Lst := Last;
      case Val.Fld is
         when F_Initial =>
            null;
         when F_Header =>
            Insert (Val.Header_Value, Ctx.Buffer.all (Buffer_First .. Buffer_Last), Offset);
         when F_Vector | F_Final =>
            null;
      end case;
   end Set_Field_Value;

   procedure Set_Header (Ctx : in out Context; Val : RFLX.Arrays.Enumeration) is
      Field_Value : constant Field_Dependent_Value := (F_Header, To_Base (Val));
      First, Last : Types.Bit_Index;
   begin
      Reset_Dependent_Fields (Ctx, F_Header);
      Set_Field_Value (Ctx, Field_Value, First, Last);
      Ctx.Message_Last := Last;
      Ctx.Cursors (F_Header) := (State => S_Valid, First => First, Last => Last, Value => Field_Value, Predecessor => Ctx.Cursors (F_Header).Predecessor);
      Ctx.Cursors (Successor (Ctx, F_Header)) := (State => S_Invalid, Predecessor => F_Header);
   end Set_Header;

   procedure Set_Vector_Empty (Ctx : in out Context) is
      First : constant Types.Bit_Index := Field_First (Ctx, F_Vector);
      Last : constant Types.Bit_Index := Field_Last (Ctx, F_Vector);
   begin
      Reset_Dependent_Fields (Ctx, F_Vector);
      Ctx.Message_Last := Last;
      Ctx.Cursors (F_Vector) := (State => S_Valid, First => First, Last => Last, Value => (Fld => F_Vector), Predecessor => Ctx.Cursors (F_Vector).Predecessor);
      Ctx.Cursors (Successor (Ctx, F_Vector)) := (State => S_Invalid, Predecessor => F_Vector);
   end Set_Vector_Empty;

   procedure Switch_To_Vector (Ctx : in out Context; Seq_Ctx : out Modular_Vector_Sequence.Context) is
      First : constant Types.Bit_Index := Field_First (Ctx, F_Vector);
      Last : constant Types.Bit_Index := Field_Last (Ctx, F_Vector);
      Buffer : Types.Bytes_Ptr;
   begin
      if Invalid (Ctx, F_Vector) then
         Reset_Dependent_Fields (Ctx, F_Vector);
         Ctx.Message_Last := Last;
         pragma Assert ((if
                            Structural_Valid (Ctx.Cursors (F_Header))
                         then
                            Ctx.Cursors (F_Header).Last - Ctx.Cursors (F_Header).First + 1 = RFLX.Arrays.Enumeration_Base'Size
                            and then Ctx.Cursors (F_Header).Predecessor = F_Initial
                            and then Ctx.Cursors (F_Header).First = Ctx.First
                            and then (if
                                         Structural_Valid (Ctx.Cursors (F_Vector))
                                      then
                                         Ctx.Cursors (F_Vector).Last - Ctx.Cursors (F_Vector).First + 1 = Ctx.Last - Ctx.First + 1 - Types.Bit_Length (Ctx.Cursors (F_Header).Last - Ctx.Cursors (F_Header).First + 1)
                                         and then Ctx.Cursors (F_Vector).Predecessor = F_Header
                                         and then Ctx.Cursors (F_Vector).First = Ctx.Cursors (F_Header).Last + 1)));
         Ctx.Cursors (F_Vector) := (State => S_Structural_Valid, First => First, Last => Last, Value => (Fld => F_Vector), Predecessor => Ctx.Cursors (F_Vector).Predecessor);
         Ctx.Cursors (Successor (Ctx, F_Vector)) := (State => S_Invalid, Predecessor => F_Vector);
      end if;
      Take_Buffer (Ctx, Buffer);
      pragma Warnings (Off, "unused assignment to ""Buffer""");
      Modular_Vector_Sequence.Initialize (Seq_Ctx, Buffer, Ctx.Buffer_First, Ctx.Buffer_Last, First, Last);
      pragma Warnings (On, "unused assignment to ""Buffer""");
   end Switch_To_Vector;

   procedure Update_Vector (Ctx : in out Context; Seq_Ctx : in out Modular_Vector_Sequence.Context) is
      Valid_Sequence : constant Boolean := Modular_Vector_Sequence.Valid (Seq_Ctx);
      Buffer : Types.Bytes_Ptr;
   begin
      Modular_Vector_Sequence.Take_Buffer (Seq_Ctx, Buffer);
      Ctx.Buffer := Buffer;
      if Valid_Sequence then
         Ctx.Cursors (F_Vector) := (State => S_Valid, First => Ctx.Cursors (F_Vector).First, Last => Ctx.Cursors (F_Vector).Last, Value => Ctx.Cursors (F_Vector).Value, Predecessor => Ctx.Cursors (F_Vector).Predecessor);
      end if;
   end Update_Vector;

end RFLX.Arrays.Generic_Array_Size_Defined_By_Message_Size;