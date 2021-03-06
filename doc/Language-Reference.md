# Language Reference

The specification language describes protocol message formats based on types. For each type of the specification language a description of its syntax and semantics and an example is given. A simple variant of Backus-Naur Form is used to describe the syntax. Reserved keywords and literals are marked in bold. The following basic elements are used to describe the syntax of the language:

*name*: A name consists of alphanumeric characters and underscores. By convention a name starts with a capital and after each underscore follows a capital as well (e.g., Mixed_Case_With_Underscores).

*number*: A number consists of numerical digits. An underscore can be added between two digits to improve readability.

*mathematical_expression*: A mathematical expression consists of numbers and names combined by mathematical operators (addition __+__, subtraction __-__, multiplication __\*__, division __/__, exponentiation __\*\*__).

*boolean_expression*: A boolean expression consists of relations (__<__, __<=__, __=__, __/=__, __>=__, __>__) between names and numbers combined by boolean operators (conjunction __and__, disjunction __or__).

## Scalar Types

### Integer Type

An integer type is used to represent numbers. Two types of integers are supported: modular type and range type.

#### Syntax

*modular_type* ::= __type__ *name* __is__ __mod__ *modulus* __;__

*range_type* ::= __type__ *name* __is__ __range__ *first* __..__ *last* __with Size =>__ *number* __;__

*modulus* ::= *mathematical_expression*

*first* ::= *mathematical_expression*

*last* ::= *mathematical_expression*

#### Static Semantics

A modular type represents the values from 0 to one less than the *modulus*. The bit size of a modular type is determined by calculating the binary logarithm of *modulus*.

The set of values of a range type consists of all numbers from the lower bound to the upper bound. For a range type the bit size has to be specified explicitly.

#### Example

```Ada RFLX declaration
type Address is mod 2**48;
type Type_Length is range 46 .. 2**16 - 1 with Size => 16;
```

### Enumeration Type

An enumeration type represents a value out of a list of possible values.

#### Syntax

*enumeration_type* ::= __type__ *name* __is__ __(__ *literals* __)__ __with__ *enumeration_aspects* __;__

*literals* ::= *literal* { __,__ *literal* }

*literal* ::= *name* [__=>__ *number*]

*enumeration_aspects* ::= *enumeration_aspect* { __,__ *enumeration_aspect* }

*enumeration_aspect* ::= *size_aspect* | *always_valid_aspect*

*size_aspect* ::= __Size =>__ *number*

*always_valid_aspect* ::= __Always_Valid__ [ __=>__ ( __True__ | __False__ ) ]

#### Static Semantics

The set of values of an enumeration type consists of the list of declared enumeration literals. Each enumeration literal has a distinct value. If no explicit value is given, the first literal is zero, and the value of each subsequent literal is incremented by one. Literals with and without explicit value must not be intermixed in one definition. The bit size of the enumeration type must be specified explicitly. Optionally, an enumeration type can be flagged as always valid. A message field with such type is always considered valid, whether or not its value corresponds to one of the specified literals.

#### Example

```Ada RFLX declaration
type Tag is (Msg_Error, Msg_Data) with Size => 1;

type Ether_Type is
   (ET_IPv4            => 16#0800#,
    ET_ARP             => 16#0806#,
    ET_VLAN_Tag        => 16#8100#,
    ET_IPv6            => 16#86DD#,
    ET_VLAN_Tag_Double => 16#9100#)
with Size => 16, Always_Valid;
```

## Message Type

A message type is a collection components. Additional then clauses allow to define conditions and dependencies between components.

#### Syntax

*message_type* ::= __type__ *name* __is__ *message_definition* __;__

*message_definition* ::= __message__ [ *null_component* ] *component* { *component* } __end message__ | __null message__

*component* ::= *component_name* __:__ *component_type*
                   [__with__ *aspects*]
                   [__if__ *condition*]
                   { *then_clause* } __;__

*null_component* ::= __null__
                         *then_clause* __;__

*then_clause* ::= __then__ *component_name*
                     [__with__ *aspects*]
                     [__if__ *condition*]

*component_name* ::= *name* | __null__

*component_type* ::= *name*

*aspects* ::= *aspect* { __,__ *aspect* }

*aspect* ::= *first_aspect* | *size_aspect*

*first_aspect* ::= __First__ __=>__ *mathematical_expression*

*size_aspect* ::= __Size__ __=>__ *mathematical_expression*

*condition* ::= *boolean_expression*

#### Static Semantics

A message type specifies the message format of a protocol. Each component corresponds to one field in a message. A then clause of a component allows to define which field follows. If no then clause is given, it is assumed that always the next component of the message follows. If no further component follows, it is assumed that the message ends with this field. The end of a message can also be denoted explicitly by adding a then clause to __null__. Optionally a then clause can contain a condition under which the corresponding field follows and aspects which allow to define the size of the next field and the location of its first bit. These aspects can also be specified in the component. Each aspect can be specified either in the component or in all incoming then clauses, but not in both. The condition can refer to previous fields (including the component containing the then clause). A condition can also be added to a component. A component condition is equivalent to adding a condition to all incoming then clauses. If a component condition as well as a condition at an incoming then clause exists, both conditions are combined by a logical conjunction. If required, a null component can be used to specify the size of the first field in the message. An empty message can be represented by a null message.

The size of a message must be a multiple of 8 bit. Opaque fields and array fields must be byte aligned.

#### Example

```Ada RFLX declaration
type Frame is
   message
      Destination : Address;
      Source : Address;
      Type_Length_TPID : Type_Length
         then TPID
            with First => Type_Length_TPID'First
            if Type_Length_TPID = 16#8100#
         then Payload
            with Size => Type_Length_TPID * 8
            if Type_Length_TPID <= 1500
         then Ether_Type
            with First => Type_Length_TPID'First
            if Type_Length_TPID >= 1536 and Type_Length_TPID /= 16#8100#;
      TPID : TPID;
      TCI : TCI;
      Ether_Type : Ether_Type
         then Payload
            with Size => Message'Last - Ether_Type'Last;
      Payload : Opaque
         then null
            if Payload'Size / 8 >= 46 and Payload'Size / 8 <= 1500;
   end message;

type Empty_Message is null message;
```

## Type Refinement

A type refinement describes the relation of a component in a message type to another message type.

#### Syntax

*type_refinement* ::= __for__ *refined_type_name* __use__ __(__ *refined_component_name* __=>__ *message_type_name* __)__ [ __if__ *condition* ] __;__

*refined_type_name* ::= *qualified_name*

*refined_component_name* ::= *name*

*message_type_name* ::= *qualified_name*

*qualified_name* ::= *name* { __.__ *name* }

*condition* ::= *boolean_expression*

#### Static Semantics

A type refinement describes under which condition a specific protocol message can be expected inside of a payload field. Only components of type `Opaque` can be refined. Types defined in other packages are referenced by a qualified name in the form package_name.message_type_name. The condition can refer to components of the refined type. To indicate that a refined component is empty (i.e. does not exit) under a certain condition, a null message can be used as message type.

#### Example

```Ada RFLX declaration
for Ethernet::Frame use (Payload => IPv4::Packet)
   if Ether_Type = Ethernet::IPV4;
```

## Type Derivation

A type derivation allows to create a new message type based on an existing message type.

#### Syntax

*type_derivation* ::= __type__ *name* __is new__ *base_type_name*__;__

*base_type_name* ::= *qualified_name*

#### Static Semantics

A derived message type derives its specification from a base type. Type refinements of a base message type are not inherited by the derived message type.

#### Example

```Ada RFLX declaration
type Specific_Extension is new Extension;
```

## Array Type

An array type represents a list of similar elements.

#### Syntax

*array_type* ::= __type__ *name* __is array of__ *element_type* __;__

*element_type* ::= *name*

#### Static Semantics

An array consists of a number of elements with similar type. Scalar types as well as message types can be used as element type. When an array is used in a message type, its bit length has to be specified by a size aspect.

#### Example

```Ada RFLX declaration
type Options is array of Option;
```

## Package

A package is used to structure a specification.

#### Syntax

*package* ::= __package__ *name* __is__ *body* __end__ *name* __;__

*body* := { *modular_type* | *range_type* | *enumeration_type* | *message_type* | *type_refinement* }

#### Static Semantics

A package is a collection of types. By convention one protocol is specified in one package.

#### Example

```Ada RFLX
package Ethernet is

   type Address is mod 2**48;
   type Type_Length is range 46 .. 2**16 - 1 with Size => 16;
   type TPID is range 16#8100# .. 16#8100# with Size => 16;
   type TCI is mod 2**16;
   type Ether_Type is
      (ET_IPv4            => 16#0800#,
       ET_ARP             => 16#0806#,
       ET_VLAN_Tag        => 16#8100#,
       ET_IPv6            => 16#86DD#,
       ET_VLAN_Tag_Double => 16#9100#)
   with Size => 16, Always_Valid;

   type Frame is
      message
         Destination : Address;
         Source : Address;
         Type_Length_TPID : Type_Length
            then TPID
               with First => Type_Length_TPID'First
               if Type_Length_TPID = 16#8100#
            then Payload
               with Size => Type_Length_TPID * 8
               if Type_Length_TPID <= 1500
            then Ether_Type
               with First => Type_Length_TPID'First
               if Type_Length_TPID >= 1536 and Type_Length_TPID /= 16#8100#;
         TPID : TPID;
         TCI : TCI;
         Ether_Type : Ether_Type
            then Payload
               with Size => Message'Last - Ether_Type'Last;
         Payload : Opaque
            then null
               if Payload'Size / 8 >= 46 and Payload'Size / 8 <= 1500;
      end message;

end Ethernet;
```

## Context Clause

The context clause is used to specify the relation to other packages and consists of a list of with clauses.

#### Syntax

*context* ::= { __with__ *package_name* __;__ }

*package_name* ::= *name*

#### Static Semantics

For each package referenced in a file, a corresponding with clause has to be added to the beginning of the file.

#### Example

```Ada RFLX context
with Ethernet;
with IPv4;
```

## File

A RecordFlux specification file is recognized by the file extension `.rflx`. Each specification file contains exactly one package. The file name must match the package name in lower case characters.

#### Syntax

*file* ::= *context* *package*

#### Example

File: `in_ethernet.rflx`

```Ada RFLX partial
with Ethernet;
with IPv4;

package In_Ethernet is

   for Ethernet::Frame use (Payload => IPv4::Packet)
      if Ether_Type = Ethernet::ET_IPv4;

end In_Ethernet;
```
