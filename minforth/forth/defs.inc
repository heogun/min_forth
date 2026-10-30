; MinOS jump table entries (RAM 0xf000..).
; Defined with #mute so they occupy no space.

#mute
#org 0xf000
_Start:
#org 0xf003
_Prompt:
#org 0xf006
_MemMove:
#org 0xf009
_Random:
#org 0xf00c
_ScanPS2:
#org 0xf00f
_ResetPS2:
#org 0xf012
_ReadInput:
#org 0xf015
_WaitInput:
#org 0xf018
_ReadLine:
#org 0xf01b
_SkipSpace:
#org 0xf01e
_ReadHex:
#org 0xf021
_FlashA:
#org 0xf024
_SerialPrint:
#org 0xf027
_FindFile:
#org 0xf02a
_LoadFile:
#org 0xf02d
_SaveFile:
#org 0xf030
_ClearVRAM:
#org 0xf033
_Clear:
#org 0xf036
_ClearRow:
#org 0xf039
_ScrollUp:
#org 0xf03c
_ScrollDn:
#org 0xf03f
_Char:
#org 0xf042
_PrintChar:
#org 0xf045
_Print:
#org 0xf048
_PrintPtr:
#org 0xf04b
_PrintHex:
#org 0xf04e
_SetPixel:
#org 0xf051
_Line:
#org 0xf054
_Rect:
#org 0xf057
_ClearPixel:
#emit

; MinOS zero-page variables we use.
#mute
#org 0x00c9
_ReadPtr:
#org 0x00cd
_ReadBuffer:
#emit

; ---------------------------------------------------------------------------
; Forth zero-page variables.  Everything lives below 0x80 so that the MinOS
; helpers we call (which use 0x80..0x95 and 0xc0..0xff) cannot clobber us.
;
; Data stack: low bytes at 0x3000+SP, high bytes at 0x3100+SP.  SP is the
; offset of the top cell; it starts at 0xfe (empty sentinel) and pushes add 2,
; so the first cell lands at offset 0.  The stack is circular with 128 cells.
; ---------------------------------------------------------------------------

#mute
#org 0x0000
zSP:                                  ; data stack offset of top cell
#org 0x0001
zNP:                                  ; scratch: SP-2 (next cell down)
#org 0x0002
zT0:
#org 0x0003
zT1:
#org 0x0004
zT2:
#org 0x0005
zT3:
#org 0x0006
zPTR:                                 ; general 16-bit pointer
#org 0x0008
zPTR2:                                ; second 16-bit pointer
#org 0x000a
zXTV:                                 ; execution token
#org 0x000c
zBASE:                                ; number base (16-bit)
#org 0x000e
zSTATE:                               ; 0=interpret, 1=compile
#org 0x000f
zHERE:                                ; dictionary allocation pointer
#org 0x0011
zLATEST:                              ; newest dictionary header
#org 0x0013
zTOK:                                 ; token buffer (32 bytes)
#org 0x0033
zTOKLEN:
#org 0x0034
zCSP:                                 ; control stack depth
#org 0x0035
zCSTK:                                ; control stack, 16 entries * 3 bytes
#org 0x0065
zNUM:                                 ; number being built / printed
#org 0x0067
zNUM2:                                ; scratch number
#org 0x0069
zTMP:
#org 0x006a
zTMP2:
#org 0x006b
zTMP3:
#org 0x006c
zTMP4:
#org 0x006d
zIMM:                                 ; FIND: immediate flag
#org 0x006e
zIVEC:                                ; pointer to interpreter input
#org 0x0070
zDIGIT:
#org 0x0071
zCOUNT:
#org 0x0072
zLVD:                                 ; compile-time loop nesting depth
#org 0x0073
zLEAVE:                               ; number of pending LEAVE patches
#org 0x0074
zLVSTK:                               ; LEAVE patch list, 0x74..0x7b (4 words)
#org 0x007c
zLFP:                                 ; loop-stack pointer to innermost frame
#org 0x007e
zLSTKP:                               ; next free loop-stack slot (starts 0x2800)
#org 0x0096
zCIDX:                                ; cached index of the innermost loop
#org 0x0098
zCLIM:                                ; cached limit of the innermost loop
#org 0x009a
zLastCall:                            ; address of the most recent compiled JPS
#org 0x009c
zTailOK:                              ; 1 only while that JPS is the last emitted code
#org 0x009d
zEndTarget:                           ; 1 when HERE is a patched forward-branch target
#org 0x26c0
nfDefHere:                            ; pre-colon dictionary checkpoint (not ZP)
#org 0x26c2
nfDefLatest:                          ; restore on abort during compilation
#emit
; Forth ZP state uses 0x00..0x7f and 0x96..0x9d. MinOS helpers use
; 0x80..0x95 and 0xc0..0xff; do not allocate Forth state in those ranges.

; ---------------------------------------------------------------------------
; Convenience macros
; ---------------------------------------------------------------------------

; Push A as the low byte and zT0 as the high byte.
%macro PUSH_AH 0
  AIZ 2,zSP
  SZP zSP,0x30
  LDZ zT0
  SZP zSP,0x31
%endmacro

; Push A as the low byte and an immediate as the high byte.
%macro PUSH_AI 1
  AIZ 2,zSP
  SZP zSP,0x30
  LDI ${1}
  SZP zSP,0x31
%endmacro

; Push a 16-bit immediate.
%macro LIT 1
  AIZ 2,zSP
  LDI >${1}
  SZP zSP,0x31
  LDI <${1}
  SZP zSP,0x30
%endmacro

; Drop the top cell.
%macro DROP1 0
  SIZ 2,zSP
%endmacro

; Increment the 16-bit pointer whose bytes live at \lo and \hi.
; INZ only bumps one byte, so propagate the carry explicitly.
%macro INCW 1
  INZ ${1}
  BNE I${__}done
  INZ ${1}+1
I${__}done:
%endmacro

; NP = SP - 2
%macro SETNP 0
  MZZ zSP,zNP
  SIZ 2,zNP
%endmacro

; SP = NP
%macro SETSPNP 0
  MZZ zNP,zSP
%endmacro
