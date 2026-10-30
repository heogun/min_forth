; ===========================================================================
; MINFORTH - a subroutine-threaded Forth for the Minimal 64x4 Redux
;
; Loaded at 0x1000 by MinOS.  Data stack lives at 0x3000/0x3100, the
; dictionary starts at 0x8000 and grows upward.  Calls are JPS to the body
; of a word; each body ends with RTS.  Literals are compiled as inline push
; sequences.  The kernel itself builds the primitive headers at boot.
; ===========================================================================

#org 0x1000

; ---------------------------------------------------------------------------
; Boot
; ---------------------------------------------------------------------------
wBoot:
        MIB 0xfe,0xffff          ; hardware return stack
        MIZ 0xfe,zSP             ; empty data stack
        MIV 0x2800,zLSTKP        ; empty loop stack
        CLV zLFP
        MIZ 10,zBASE
        CLZ zBASE+1
        CLZ zSTATE
        CLZ zLVD
        CLZ zLEAVE
        MIV 0x8000,zHERE
        CLV zLATEST
        JPS nf_build
        JPS nf_banner
wRepl:
        ; _ReadLine needs _ReadPtr to point at the insertion point in its
        ; buffer, but MinOS's print helpers clobber _ReadPtr.  Keep our own
        ; parsing cursor in a private ZP pair (zIVEC) and refresh it from
        ; the buffer start each time _ReadLine has collected a line.
        MIV _ReadBuffer,_ReadPtr
        JPS _ReadLine
        MIV _ReadBuffer,zIVEC
        JPS nf_interpret
        JPA wRepl

nf_banner:
        JPS _Print "MINFORTH 64x4  (type words, : name ... ;)", 10, 0
        RTS

; ---------------------------------------------------------------------------
; Dictionary construction from the primitive table
;
; Table entry: [len|imm][xt_lo][xt_hi][name bytes...], terminated by len=0.
; Header:      [len|imm][link_lo][link_hi][xt_lo][xt_hi][name bytes...]
; ---------------------------------------------------------------------------
nf_build:
        MIV 0x8000,zHERE
        CLV zLATEST
        MIV primtab,zPTR2
nfb_loop:
        LDT zPTR2
        CPI 0
        BEQ nfb_done
        JPS nf_newprim
        JPA nfb_loop
nfb_done:
        RTS

nf_newprim:
        LDZ zHERE SDZ zPTR
        LDZ zHERE+1 SDZ zPTR+1
        ; length
        LDT zPTR2
        SDZ zT0
        SDT zPTR
        INCW zPTR
        INCW zPTR2
        ; link
        LDZ zLATEST SDT zPTR
        INCW zPTR
        LDZ zLATEST+1 SDT zPTR
        INCW zPTR
        ; xt
        LDT zPTR2 SDT zPTR
        INCW zPTR
        INCW zPTR2
        LDT zPTR2 SDT zPTR
        INCW zPTR
        INCW zPTR2
        ; name
        LDZ zT0
        ANI 0x1f
        SDZ zCOUNT
nfb_copy:
        LDT zPTR2
        SDT zPTR
        INCW zPTR
        INCW zPTR2
        DEZ zCOUNT
        BNE nfb_copy
        ; publish
        LDZ zHERE SDZ zLATEST
        LDZ zHERE+1 SDZ zLATEST+1
        LDZ zPTR SDZ zHERE
        LDZ zPTR+1 SDZ zHERE+1
        RTS

; ---------------------------------------------------------------------------
; Tokenizer: fetch the next token from (zIVEC) into zTOK/zTOKLEN.
; Returns A=1 if a token was found, A=0 at end of line.
; ---------------------------------------------------------------------------
nf_next:
nfn_skip:
        LDT zIVEC
        CPI 10 BEQ nfn_none
        CPI 0 BEQ nfn_none
        CPI 32 BEQ nfn_adv
        CPI 9 BEQ nfn_adv
        CPI 92 BEQ nfn_comment
        CPI 40 BEQ nfn_paren
        JPA nfn_start
nfn_adv:
        INCW zIVEC
        JPA nfn_skip
nfn_comment:
        LDT zIVEC
        CPI 10 BEQ nfn_none
        CPI 0 BEQ nfn_none
        INCW zIVEC
        JPA nfn_comment
nfn_paren:
        LDT zIVEC
        CPI 41 BEQ nfn_parend
        CPI 10 BEQ nfn_none
        CPI 0 BEQ nfn_none
        INCW zIVEC
        JPA nfn_paren
nfn_parend:
        INCW zIVEC
        JPA nfn_skip
nfn_start:
        MIV zTOK,zPTR
        CLZ zTOKLEN
nfn_char:
        LDT zIVEC
        CPI 10 BEQ nfn_done
        CPI 0 BEQ nfn_done
        CPI 32 BEQ nfn_done
        CPI 9 BEQ nfn_done
        CPI 97 BCC nfn_store
        CPI 123 BCS nfn_store
        SUI 32
nfn_store:
        SDT zPTR
        INCW zPTR
        INZ zTOKLEN
        INCW zIVEC
        JPA nfn_char
nfn_done:
        LDI 1
        RTS
nfn_none:
        LDI 0
        RTS

; Interpret the whole current line.
nf_interpret:
nfi_loop:
        JPS nf_next
        CPI 0
        BEQ nfi_done
        JPS nf_word
        JPA nfi_loop
nfi_done:
        RTS

; ---------------------------------------------------------------------------
; FIND.  Input zTOK/zTOKLEN.  Output zXTV, zIMM, A=1 found / A=0 not found.
; Uses zTMP/zTMP2 (cursor), zTMP3 (raw len), zTMP4 (masked len).
; ---------------------------------------------------------------------------
nf_find:
        LDZ zLATEST SDZ zTMP
        LDZ zLATEST+1 SDZ zTMP2
nff_loop:
        LDZ zTMP
        ORZ zTMP2
        CPI 0
        BEQ nff_no
        LDZ zTMP SDZ zPTR
        LDZ zTMP2 SDZ zPTR+1
        LDT zPTR
        SDZ zTMP3
        ANI 0x1f
        SDZ zTMP4
        CPZ zTOKLEN
        BNE nff_next
        AIV 5,zPTR
        MIV zTOK,zPTR2
        LDZ zTMP4 SDZ zCOUNT
nff_cmp:
        LDT zPTR
        SDZ zT1
        LDT zPTR2
        CPZ zT1
        BNE nff_next
        INCW zPTR
        INCW zPTR2
        DEZ zCOUNT
        BNE nff_cmp
        ; found: xt at header+3
        LDZ zTMP SDZ zPTR
        LDZ zTMP2 SDZ zPTR+1
        AIV 3,zPTR
        LDT zPTR SDZ zXTV
        INCW zPTR
        LDT zPTR SDZ zXTV+1
        LDZ zTMP3
        ANI 0x80
        SDZ zIMM
        LDI 1
        RTS
nff_next:
        LDZ zTMP SDZ zPTR
        LDZ zTMP2 SDZ zPTR+1
        AIV 1,zPTR
        LDT zPTR SDZ zTMP
        INCW zPTR
        LDT zPTR SDZ zTMP2
        JPA nff_loop
nff_no:
        LDI 0
        RTS

; ---------------------------------------------------------------------------
; Execute one token: interpret or compile.
; ---------------------------------------------------------------------------
nf_word:
        JPS nf_find
        CPI 0
        BEQ nfw_number
        LDZ zSTATE
        CPI 0
        BEQ nfw_exec
        LDZ zIMM
        CPI 0
        BNE nfw_exec
        JPS nf_ccall
        RTS
nfw_exec:
        JPS nf_runxt
        RTS
nfw_number:
        JPS nf_parse
        CPI 0
        BEQ nfw_err
        LDZ zSTATE
        CPI 0
        BEQ nfw_push
        JPS nf_clit
        RTS
nfw_push:
        AIZ 2,zSP
        LDZ zNUM
        SZP zSP,0x30
        LDZ zNUM+1
        SZP zSP,0x31
        RTS
nfw_err:
        JPS _Print " ?", 10, 0
        RTS

; ---------------------------------------------------------------------------
; Number parser.  Input zTOK/zTOKLEN, output zNUM and A=1 (valid) / A=0.
; Supports an optional leading '-' and the current BASE.
; ---------------------------------------------------------------------------
nf_parse:
        CLV zNUM
        CLZ zTMP3
        MIV zTOK,zPTR2
        LDZ zTOKLEN
        CPI 0
        BEQ npf_fail
        SDZ zCOUNT
        LDT zPTR2
        CPI 45
        BNE npf_loop
        LDI 1
        SDZ zTMP3
        INCW zPTR2
        DEZ zCOUNT
        BEQ npf_fail
npf_loop:
        LDZ zCOUNT
        CPI 0
        BEQ npf_finish
        LDT zPTR2
        CPI 48 BCC npf_fail
        CPI 58 BCC npf_dec
        CPI 65 BCC npf_fail
        CPI 71 BCC npf_hex
        JPA npf_fail
npf_dec:
        SUI 48
        JPA npf_have
npf_hex:
        SUI 55
npf_have:
        SDZ zDIGIT
        CPZ zBASE
        BCS npf_fail
        CLV zNUM2
        LDZ zBASE
        SDZ zTMP2
npf_mul:
        LDZ zNUM
        ADZ zNUM2
        SDZ zNUM2
        LDZ zNUM+1
        ACZ zNUM2+1
        SDZ zNUM2+1
        DEZ zTMP2
        BNE npf_mul
        LDZ zNUM2
        ADZ zDIGIT
        SDZ zNUM
        LDZ zNUM2+1
        ACI 0
        SDZ zNUM+1
        INCW zPTR2
        DEZ zCOUNT
        JPA npf_loop
npf_finish:
        LDZ zTMP3
        CPI 0
        BEQ npf_ok
        LDZ zNUM
        SDZ zT0
        CLD
        SUZ zT0
        SDZ zNUM
        LDZ zNUM+1
        SDZ zT1
        CLD
        SCZ zT1
        SDZ zNUM+1
npf_ok:
        LDI 1
        RTS
npf_fail:
        LDI 0
        RTS

; ---------------------------------------------------------------------------
; Emit helpers
; ---------------------------------------------------------------------------
nf_cbyte:                       ; A -> *HERE, HERE++
        SDZ zTMP2                ; save the byte: the pointer setup below
                                 ; uses A, so it must not be clobbered
        LDZ zHERE SDZ zPTR
        LDZ zHERE+1 SDZ zPTR+1
        LDZ zTMP2 SDT zPTR
        INCW zPTR
        LDZ zPTR SDZ zHERE
        LDZ zPTR+1 SDZ zHERE+1
        RTS

nf_cword:                       ; zT0 (lo), zT1 (hi) -> *HERE
        LDZ zT0 JAS nf_cbyte
        LDZ zT1 JAS nf_cbyte
        RTS

nf_ccall:                       ; compile JPS zXTV
        LDI 0x69 JAS nf_cbyte
        LDZ zXTV SDZ zT0
        LDZ zXTV+1 SDZ zT1
        JPS nf_cword
        RTS

nf_clit:                        ; compile inline push of zNUM
        LDI 0xbc JAS nf_cbyte
        LDI 2 JAS nf_cbyte
        LDI <zSP JAS nf_cbyte
        LDI 0x76 JAS nf_cbyte
        LDZ zNUM+1 JAS nf_cbyte
        LDI 0x83 JAS nf_cbyte
        LDI <zSP JAS nf_cbyte
        LDI 0x31 JAS nf_cbyte
        LDI 0x76 JAS nf_cbyte
        LDZ zNUM JAS nf_cbyte
        LDI 0x83 JAS nf_cbyte
        LDI <zSP JAS nf_cbyte
        LDI 0x30 JAS nf_cbyte
        RTS

nf_runxt:                       ; call the word whose xt is in zXTV
        ; PHS pushes one byte; RTS reads the high byte from the lower
        ; address, so push the low byte first (same order as JPS).  RTS
        ; also skips the two operand bytes of a JPS, hence the -2.
        LDI <nfr_ret-2 PHS
        LDI >nfr_ret-2 PHS
        JPR zXTV
nfr_ret:
        RTS

; Create a header for the current token; body = header+5+len.
nf_create:
        LDZ zHERE SDZ zPTR
        LDZ zHERE+1 SDZ zPTR+1
        LDZ zTOKLEN SDT zPTR
        INCW zPTR
        LDZ zLATEST SDT zPTR
        INCW zPTR
        LDZ zLATEST+1 SDT zPTR
        INCW zPTR
        ; xt = HERE + 5 + len
        LDZ zTOKLEN
        ADI 5
        SDZ zT0
        LDZ zHERE
        ADZ zT0
        SDZ zT1
        LDZ zHERE+1
        ACI 0
        SDZ zT2
        LDZ zT1 SDT zPTR
        INCW zPTR
        LDZ zT2 SDT zPTR
        INCW zPTR
        MIV zTOK,zPTR2
        LDZ zTOKLEN SDZ zCOUNT
nfc_copy:
        LDT zPTR2
        SDT zPTR
        INCW zPTR
        INCW zPTR2
        DEZ zCOUNT
        BNE nfc_copy
        LDZ zHERE SDZ zLATEST
        LDZ zHERE+1 SDZ zLATEST+1
        LDZ zPTR SDZ zHERE
        LDZ zPTR+1 SDZ zHERE+1
        RTS

; ---------------------------------------------------------------------------
; Control-flow stack helpers.
; Entry: type (0..255), address (2 bytes).
; ---------------------------------------------------------------------------
nf_cspush:                      ; A=type, zT0/zT1=address
        SDZ zT2
        LDZ zCSP
        SDZ zTMP
        ADZ zTMP
        ADZ zTMP
        ADI <zCSTK
        SDZ zPTR
        CLZ zPTR+1
        LDZ zT2 SDT zPTR
        INCW zPTR
        LDZ zT0 SDT zPTR
        INCW zPTR
        LDZ zT1 SDT zPTR
        INZ zCSP
        RTS

nf_cspop:                       ; -> A=type, zT0/zT1=address
        DEZ zCSP
        LDZ zCSP
        SDZ zTMP
        ADZ zTMP
        ADZ zTMP
        ADI <zCSTK
        SDZ zPTR
        CLZ zPTR+1
        LDT zPTR SDZ zT2
        INCW zPTR
        LDT zPTR SDZ zT0
        INCW zPTR
        LDT zPTR SDZ zT1
        LDZ zT2
        RTS

; ---------------------------------------------------------------------------
; Primitive: stack
; ---------------------------------------------------------------------------
wDUP:
        MZZ zSP,zNP
        AIZ 2,zSP
        LZP zNP,0x30
        SZP zSP,0x30
        LZP zNP,0x31
        SZP zSP,0x31
        RTS

wDROP:
        SIZ 2,zSP
        RTS

wSWAP:
        SETNP
        LZP zNP,0x30 SDZ zT0
        LZP zNP,0x31 SDZ zT1
        LZP zSP,0x30 SDZ zT2
        LZP zSP,0x31 SDZ zT3
        LDZ zT2 SZP zNP,0x30
        LDZ zT3 SZP zNP,0x31
        LDZ zT0 SZP zSP,0x30
        LDZ zT1 SZP zSP,0x31
        RTS

wOVER:
        SETNP
        AIZ 2,zSP
        LZP zNP,0x30 SZP zSP,0x30
        LZP zNP,0x31 SZP zSP,0x31
        RTS

wROT:
        ; c -> T2/T3, b -> c, a -> b, c -> a
        LZP zSP,0x30 SDZ zT2
        LZP zSP,0x31 SDZ zT3
        MZZ zSP,zNP
        SIZ 2,zNP
        LZP zNP,0x30 SZP zSP,0x30
        LZP zNP,0x31 SZP zSP,0x31
        MZZ zSP,zTMP
        SIZ 4,zTMP
        LZP zTMP,0x30 SDZ zT0
        LZP zTMP,0x31 SDZ zT1
        MZZ zSP,zTMP
        SIZ 2,zTMP
        LDZ zT0 SZP zTMP,0x30
        LDZ zT1 SZP zTMP,0x31
        MZZ zSP,zTMP
        SIZ 4,zTMP
        LDZ zT2 SZP zTMP,0x30
        LDZ zT3 SZP zTMP,0x31
        RTS

wNIP:
        SETNP
        LZP zSP,0x30 SZP zNP,0x30
        LZP zSP,0x31 SZP zNP,0x31
        SETSPNP
        RTS

; ---------------------------------------------------------------------------
; Primitive: arithmetic
; ---------------------------------------------------------------------------
wADD:
        SETNP
        LZP zSP,0x30 SDZ zT0
        LZP zSP,0x31 SDZ zT1
        LZP zNP,0x30
        ADZ zT0
        SZP zNP,0x30
        LZP zNP,0x31
        ACZ zT1
        SZP zNP,0x31
        SETSPNP
        RTS

wSUB:
        SETNP
        LZP zSP,0x30 SDZ zT0
        LZP zSP,0x31 SDZ zT1
        LZP zNP,0x30
        SUZ zT0
        SZP zNP,0x30
        LZP zNP,0x31
        SCZ zT1
        SZP zNP,0x31
        SETSPNP
        RTS

wAND:
        SETNP
        LZP zSP,0x30 SDZ zT0
        LZP zNP,0x30
        ANZ zT0
        SZP zNP,0x30
        LZP zSP,0x31 SDZ zT0
        LZP zNP,0x31
        ANZ zT0
        SZP zNP,0x31
        SETSPNP
        RTS

wOR:
        SETNP
        LZP zSP,0x30 SDZ zT0
        LZP zNP,0x30
        ORZ zT0
        SZP zNP,0x30
        LZP zSP,0x31 SDZ zT0
        LZP zNP,0x31
        ORZ zT0
        SZP zNP,0x31
        SETSPNP
        RTS

wXOR:
        SETNP
        LZP zSP,0x30 SDZ zT0
        LZP zNP,0x30
        XRZ zT0
        SZP zNP,0x30
        LZP zSP,0x31 SDZ zT0
        LZP zNP,0x31
        XRZ zT0
        SZP zNP,0x31
        SETSPNP
        RTS

wINV:
        LZP zSP,0x30
        NOT
        SZP zSP,0x30
        LZP zSP,0x31
        NOT
        SZP zSP,0x31
        RTS

wNEG:
        LZP zSP,0x30 SDZ zT0
        CLD
        SUZ zT0
        SZP zSP,0x30
        LZP zSP,0x31 SDZ zT1
        CLD
        SCZ zT1
        SZP zSP,0x31
        RTS

wINC:
        LZP zSP,0x30
        ADI 1
        SZP zSP,0x30
        LZP zSP,0x31
        ACI 0
        SZP zSP,0x31
        RTS

wDEC:
        LZP zSP,0x30
        SUI 1
        SZP zSP,0x30
        LZP zSP,0x31
        SCI 0
        SZP zSP,0x31
        RTS

w2MUL:
        LZP zSP,0x30 SDZ zT0
        LZP zSP,0x31 SDZ zT1
        LDZ zT0
        ADZ zT0
        SZP zSP,0x30
        LDZ zT1
        ACZ zT1
        SZP zSP,0x31
        RTS

; 16-bit multiply by shift/add:  ( a b -- a*b )
; zT0/zT1 = multiplicand, zT2/zT3 = multiplier, zNUM = result.
wMUL:
        SETNP
        LZP zNP,0x30 SDZ zT0
        LZP zNP,0x31 SDZ zT1
        LZP zSP,0x30 SDZ zT2
        LZP zSP,0x31 SDZ zT3
        CLV zNUM
        LDI 16
        SDZ zCOUNT
wml_loop:
        LDZ zT2
        ANI 1
        CPI 0
        BEQ wml_skip
        LDZ zNUM
        ADZ zT0
        SDZ zNUM
        LDZ zNUM+1
        ACZ zT1
        SDZ zNUM+1
wml_skip:
        ; multiplicand <<= 1
        LDZ zT0
        ADZ zT0
        SDZ zT0
        LDZ zT1
        ACZ zT1
        SDZ zT1
        ; multiplier >>= 1
        LDZ zT3
        LR1
        SDZ zT3
        LDZ zT2
        RR1
        SDZ zT2
        DEZ zCOUNT
        BNE wml_loop
        LDZ zNUM SZP zNP,0x30
        LDZ zNUM+1 SZP zNP,0x31
        SETSPNP
        RTS

; Unsigned 16-bit divide.  Inputs: dividend at zNP, divisor at zSP.
; Outputs: zNUM = quotient, zNUM2 = remainder.  Restoring long division.
nf_divmod:
        LZP zNP,0x30 SDZ zT0      ; dividend lo
        LZP zNP,0x31 SDZ zT1      ; dividend hi
        LZP zSP,0x30 SDZ zTMP     ; divisor lo
        LZP zSP,0x31 SDZ zTMP2    ; divisor hi
        CLV zT2                   ; remainder
        CLV zNUM                  ; quotient
        LDI 16
        SDZ zCOUNT
dvd_loop:
        LDZ zT1
        ANI 0x80
        SDZ zTMP3                 ; msb of the dividend
        ; remainder <<= 1
        LDZ zT2
        ADZ zT2
        SDZ zT2
        LDZ zT3
        ACZ zT3
        SDZ zT3
        LDZ zTMP3
        CPI 0
        BEQ dvd_nomsb
        INZ zT2                   ; shift the dividend msb in
dvd_nomsb:
        ; dividend <<= 1
        LDZ zT0
        ADZ zT0
        SDZ zT0
        LDZ zT1
        ACZ zT1
        SDZ zT1
        ; if remainder >= divisor: remainder -= divisor, quotient bit = 1
        LDZ zT3
        CPZ zTMP2
        BCC dvd_less
        BNE dvd_ge
        LDZ zT2
        CPZ zTMP
        BCC dvd_less
dvd_ge:
        LDZ zT2
        SUZ zTMP
        SDZ zT2
        LDZ zT3
        SCZ zTMP2
        SDZ zT3
        LDZ zNUM
        ADZ zNUM
        SDZ zNUM
        LDZ zNUM+1
        ACZ zNUM+1
        SDZ zNUM+1
        INZ zNUM
        JPA dvd_next
dvd_less:
        LDZ zNUM
        ADZ zNUM
        SDZ zNUM
        LDZ zNUM+1
        ACZ zNUM+1
        SDZ zNUM+1
dvd_next:
        DEZ zCOUNT
        BNE dvd_loop
        LDZ zT2
        SDZ zNUM2
        LDZ zT3
        SDZ zNUM2+1
        RTS

wDIV:
        SETNP
        JPS nf_divmod
        SETNP
        LDZ zNUM SZP zNP,0x30
        LDZ zNUM+1 SZP zNP,0x31
        SETSPNP
        RTS

wMOD:
        SETNP
        JPS nf_divmod
        SETNP
        LDZ zNUM2 SZP zNP,0x30
        LDZ zNUM2+1 SZP zNP,0x31
        SETSPNP
        RTS

w2DIV:
        LZP zSP,0x31 SDZ zT0
        LDZ zT0
        ANI 0x80
        SDZ zT1
        LDZ zT0
        LR1
        ORZ zT1
        SZP zSP,0x31
        LZP zSP,0x30
        RR1
        SZP zSP,0x30
        RTS

; ---------------------------------------------------------------------------
; Primitive: comparisons (results are 0 or 0xffff)
; ---------------------------------------------------------------------------
wEQ:
        SETNP
        LZP zSP,0x30 SDZ zT0
        LZP zSP,0x31 SDZ zT1
        LZP zNP,0x30
        CPZ zT0
        BNE nfe_false
        LZP zNP,0x31
        CPZ zT1
        BNE nfe_false
nfe_true:
        LDI 0xff SZP zNP,0x30
        SZP zNP,0x31
        SETSPNP
        RTS
nfe_false:
        LDI 0 SZP zNP,0x30
        SZP zNP,0x31
        SETSPNP
        RTS

wNE:
        JPS wEQ
        JPS wZEQ
        RTS

wLT:
        SETNP
        LZP zSP,0x30 SDZ zT0
        LZP zSP,0x31 SDZ zT1
        LZP zNP,0x30
        SUZ zT0
        LZP zNP,0x31
        SCZ zT1
        BCC nfl_true
        LDI 0 SZP zNP,0x30
        SZP zNP,0x31
        SETSPNP
        RTS
nfl_true:
        LDI 0xff SZP zNP,0x30
        SZP zNP,0x31
        SETSPNP
        RTS

wGT:
        JPS wSWAP
        JPS wLT
        RTS

wGE:
        JPS wLT
        JPS wZEQ
        RTS

wLE:
        JPS wGT
        JPS wZEQ
        RTS

wZEQ:
        LZP zSP,0x30 SDZ zT0
        LZP zSP,0x31
        ORZ zT0
        CPI 0
        BEQ nfz_true
        LDI 0 SZP zSP,0x30
        SZP zSP,0x31
        RTS
nfz_true:
        LDI 0xff SZP zSP,0x30
        SZP zSP,0x31
        RTS

wZLT:
        ; unsigned 0 < n  ==  n != 0
        JPS wZEQ
        JPS wZEQ
        RTS

; ---------------------------------------------------------------------------
; Primitive: memory
; ---------------------------------------------------------------------------
wFETCH:
        LZP zSP,0x30 SDZ zPTR
        LZP zSP,0x31 SDZ zPTR+1
        LDT zPTR
        SZP zSP,0x30
        INCW zPTR
        LDT zPTR
        SZP zSP,0x31
        RTS

wSTORE:
        SETNP
        LZP zSP,0x30 SDZ zPTR
        LZP zSP,0x31 SDZ zPTR+1
        LZP zNP,0x30
        SDT zPTR
        INCW zPTR
        LZP zNP,0x31
        SDT zPTR
        SETSPNP
        SIZ 2,zSP              ; consume both value and address
        RTS

wCFETCH:
        LZP zSP,0x30 SDZ zPTR
        LZP zSP,0x31 SDZ zPTR+1
        LDT zPTR
        SZP zSP,0x30
        LDI 0 SZP zSP,0x31
        RTS

wCSTORE:
        SETNP
        LZP zSP,0x30 SDZ zPTR
        LZP zSP,0x31 SDZ zPTR+1
        LZP zNP,0x30
        SDT zPTR
        SETSPNP
        SIZ 2,zSP              ; consume both value and address
        RTS

wADDSTORE:
        SETNP
        LZP zSP,0x30 SDZ zPTR
        LZP zSP,0x31 SDZ zPTR+1
        LDZ zPTR SDZ zPTR2
        LDZ zPTR+1 SDZ zPTR2+1
        AIV 1,zPTR2
        LZP zNP,0x30 SDZ zT0
        LZP zNP,0x31 SDZ zT1
        LDT zPTR
        ADZ zT0
        SDT zPTR
        LDT zPTR2
        ACZ zT1
        SDT zPTR2
        SETSPNP
        SIZ 2,zSP              ; consume both value and address
        RTS

; ---------------------------------------------------------------------------
; Primitive: return stack
; ---------------------------------------------------------------------------
wTOR:
        PLS SDZ zT0
        PLS SDZ zT1
        LZP zSP,0x31
        PHS
        LZP zSP,0x30
        PHS
        SIZ 2,zSP
        LDZ zT1 PHS
        LDZ zT0 PHS
        RTS

wFROMR:
        AIZ 2,zSP
        LDS 3                 ; value low (return address occupies +1/+2)
        SZP zSP,0x30
        LDS 4                 ; value high
        SZP zSP,0x31
        PLS SDZ zT0
        PLS SDZ zT1
        PLS
        PLS
        LDZ zT1 PHS
        LDZ zT0 PHS
        RTS

wRFETCH:
        AIZ 2,zSP
        LDS 3                 ; value low (return address occupies +1/+2)
        SZP zSP,0x30
        LDS 4                 ; value high
        SZP zSP,0x31
        RTS

; ---------------------------------------------------------------------------
; DO ... LOOP runtime.
;
; Loop frames live in RAM at 0x2800 and are linked through the previous-frame
; pointer, so nesting costs no index arithmetic at runtime:
;   +0 limit lo  +1 limit hi  +2 index lo  +3 index hi  +4 prev lo  +5 prev hi
; zLFP points at the innermost frame (0 when there is none), zLSTKP at the
; next free slot.
; ---------------------------------------------------------------------------
wDORUN:                         ; ( limit start -- )
        LZP zSP,0x30 SDZ zT0    ; start lo
        LZP zSP,0x31 SDZ zT1    ; start hi
        SIZ 2,zSP
        LZP zSP,0x30 SDZ zT2    ; limit lo
        LZP zSP,0x31 SDZ zT3    ; limit hi
        SIZ 2,zSP
        ; flush the current (outer) loop's cached index into its frame
        LDZ zLFP
        ORZ zLFP+1
        CPI 0
        BEQ wdr_noflush
        LDZ zLFP SDZ zPTR
        LDZ zLFP+1 SDZ zPTR+1
        AIV 2,zPTR
        LDZ zCIDX SDT zPTR
        INCW zPTR
        LDZ zCIDX+1 SDT zPTR
wdr_noflush:
        LDZ zLSTKP SDZ zPTR
        LDZ zLSTKP+1 SDZ zPTR+1
        LDZ zT2 SDT zPTR
        INCW zPTR
        LDZ zT3 SDT zPTR
        INCW zPTR
        LDZ zT0 SDT zPTR
        INCW zPTR
        LDZ zT1 SDT zPTR
        INCW zPTR
        LDZ zLFP SDT zPTR
        INCW zPTR
        LDZ zLFP+1 SDT zPTR
        LDZ zLSTKP SDZ zLFP
        LDZ zLSTKP+1 SDZ zLFP+1
        LDZ zT2 SDZ zCLIM
        LDZ zT3 SDZ zCLIM+1
        LDZ zT0 SDZ zCIDX
        LDZ zT1 SDZ zCIDX+1
        LDZ zLSTKP
        ADI 6
        SDZ zLSTKP
        LDZ zLSTKP+1
        ACI 0
        SDZ zLSTKP+1
        RTS

nf_lpop:                        ; pop the innermost loop frame
        LDZ zLFP SDZ zPTR
        LDZ zLFP+1 SDZ zPTR+1
        AIV 4,zPTR
        LDT zPTR SDZ zLFP
        INCW zPTR
        LDT zPTR SDZ zLFP+1
        LDZ zLSTKP
        SUI 6
        SDZ zLSTKP
        LDZ zLSTKP+1
        SCI 0
        SDZ zLSTKP+1
        ; restore the outer loop's cached index/limit
        LDZ zLFP
        ORZ zLFP+1
        CPI 0
        BEQ nflp_nocache
        LDZ zLFP SDZ zPTR
        LDZ zLFP+1 SDZ zPTR+1
        LDT zPTR SDZ zCLIM
        INCW zPTR
        LDT zPTR SDZ zCLIM+1
        INCW zPTR
        LDT zPTR SDZ zCIDX
        INCW zPTR
        LDT zPTR SDZ zCIDX+1
nflp_nocache:
        RTS

wDROPFRAME:
        JPS nf_lpop
        RTS

wI:
        AIZ 2,zSP
        LDZ zCIDX
        SZP zSP,0x30
        LDZ zCIDX+1
        SZP zSP,0x31
        RTS

wJ:                             ; index of the enclosing loop
        AIZ 2,zSP
        LDZ zLFP SDZ zPTR
        LDZ zLFP+1 SDZ zPTR+1
        AIV 4,zPTR            ; frame+4 = previous frame
        LDT zPTR SDZ zTMP
        INCW zPTR
        LDT zPTR SDZ zTMP2
        LDZ zTMP SDZ zPTR
        LDZ zTMP2 SDZ zPTR+1
        AIV 2,zPTR            ; previous frame+2 = its index
        LDT zPTR SZP zSP,0x30
        INCW zPTR
        LDT zPTR SZP zSP,0x31
        RTS

; Runtime for ." : the inline string (length byte + chars) directly follows
; the JPS in the code stream.  Print it, then move the return address past it.
wDOTQRT:
        LDS 2 SDZ zPTR        ; JPS return value = inline start - 2
        LDS 1 SDZ zPTR+1
        AIV 2,zPTR            ; -> inline length byte
        LDT zPTR SDZ zCOUNT
        INCW zPTR
        LDZ zCOUNT
        CPI 0
        BEQ wdqr_done
wdqr_loop:
        LDT zPTR SDZ zTMP
        LDZ zTMP JAS _PrintChar
        INCW zPTR
        DEZ zCOUNT
        BNE wdqr_loop
wdqr_done:
        ; RTS sets PC = return address + 2, and zPTR now points just past
        ; the string, so store (zPTR - 2) to resume right after it.
        LDZ zPTR
        SUI 2
        SDS 2
        LDZ zPTR+1
        SCI 0
        SDS 1
        RTS

wWORDS:
        LDZ zLATEST SDZ zPTR
        LDZ zLATEST+1 SDZ zPTR+1
ww_loop:
        LDZ zPTR
        ORZ zPTR+1
        CPI 0
        BEQ ww_done
        LDZ zPTR SDZ zTMP2
        LDZ zPTR+1 SDZ zTMP3
        LDT zTMP2             ; length byte lives at header+0
        ANI 0x1f
        SDZ zCOUNT
        AIV 5,zTMP2           ; names start at header+5
ww_print:
        LDT zTMP2
        JAS _PrintChar
        INCW zTMP2
        DEZ zCOUNT
        BNE ww_print
        LDI 32
        JAS _PrintChar
        ; follow the link
        LDZ zPTR SDZ zTMP2
        LDZ zPTR+1 SDZ zTMP3
        INCW zTMP2
        LDT zTMP2 SDZ zTMP4
        INCW zTMP2
        LDT zTMP2 SDZ zTMP3
        LDZ zTMP4 SDZ zPTR
        LDZ zTMP3 SDZ zPTR+1
        JPA ww_loop
ww_done:
        LDI 10
        JAS _PrintChar
        RTS

wEXEC:
        LZP zSP,0x30 SDZ zXTV
        LZP zSP,0x31 SDZ zXTV+1
        SIZ 2,zSP
        JPS nf_runxt
        RTS

; ---------------------------------------------------------------------------
; Primitive: output
; ---------------------------------------------------------------------------
wEMIT:
        LZP zSP,0x30 SDZ zT0
        SIZ 2,zSP
        LDZ zT0
        JAS _PrintChar
        RTS

wCR:
        LDI 10
        JAS _PrintChar
        RTS

wSPACE:
        LDI 32
        JAS _PrintChar
        RTS

wTYPE:
        SETNP
        LZP zNP,0x30 SDZ zPTR
        LZP zNP,0x31 SDZ zPTR+1
        LZP zSP,0x30 SDZ zCOUNT
        SETSPNP
        SIZ 2,zSP
nft_loop:
        LDZ zCOUNT
        CPI 0
        BEQ nft_done
        LDT zPTR
        JAS _PrintChar
        INCW zPTR
        DEZ zCOUNT
        JPA nft_loop
nft_done:
        RTS

wDOT:
        LZP zSP,0x30 SDZ zNUM
        LZP zSP,0x31 SDZ zNUM+1
        SIZ 2,zSP
        JPS nf_print
        LDI 32
        JAS _PrintChar
        RTS

nf_print:                       ; print zNUM in the current base (2..36)
        MIV 0x27e0,zPTR2        ; digit buffer, below the loop stack
        CLZ zCOUNT
np_digit:
        CLV zNUM2               ; quotient = repeated-subtraction count
np_sub:
        LDZ zNUM+1
        CPI 0
        BNE np_sub_do
        LDZ zNUM
        CPZ zBASE
        BCC np_done             ; zNUM < base: zNUM is the remainder
np_sub_do:
        LDZ zNUM
        SUZ zBASE
        SDZ zNUM
        LDZ zNUM+1
        SCI 0
        SDZ zNUM+1
        INZ zNUM2
        BNE np_sub
        INZ zNUM2+1
        JPA np_sub
np_done:
        LDZ zNUM                ; digit character
        CPI 10
        BCC np_digdec
        ADI 55                  ; 'A' - 10
        JPA np_putdigit
np_digdec:
        ADI 48
np_putdigit:
        SDT zPTR2
        INCW zPTR2
        INZ zCOUNT
        LDZ zNUM2 SDZ zNUM      ; continue with the quotient
        LDZ zNUM2+1 SDZ zNUM+1
        LDZ zNUM
        ORZ zNUM+1
        CPI 0
        BNE np_digit
np_rev:
        DEZ zPTR2
        LDT zPTR2
        JAS _PrintChar
        DEZ zCOUNT
        BNE np_rev
        RTS

; ---------------------------------------------------------------------------
; Compiler words
; ---------------------------------------------------------------------------
wCOLON:
        JPS nf_next
        CPI 0
        BEQ nfc_done
        MZB zHERE,nfDefHere
        MZB zHERE+1,nfDefHere+1
        MZB zLATEST,nfDefLatest
        MZB zLATEST+1,nfDefLatest+1
        JPS nf_create
        LDI 1
        SDZ zSTATE
nfc_done:
        RTS

wSEMI:
        LDI 0x6b JAS nf_cbyte
        CLZ zSTATE
        RTS

wIFRT:
        ; The pop must not be the last flag-latching operation: RTS does
        ; not touch FR, and the caller branches on the value we return.
        ; Save the cell, pop it, then latch flags from the OR of its bytes.
        LZP zSP,0x30 SDZ zT0
        LZP zSP,0x31 SDZ zT1
        SIZ 2,zSP
        LDZ zT0
        ORZ zT1
        CPI 0
        RTS

wIF:
        LDI 0x69 JAS nf_cbyte
        LDI <wIFRT JAS nf_cbyte
        LDI >wIFRT JAS nf_cbyte
        LDI 0x5f JAS nf_cbyte
        LDZ zHERE SDZ zT0
        LDZ zHERE+1 SDZ zT1
        LDI 0 JAS nf_cbyte
        LDI 0 JAS nf_cbyte
        LDI 1
        JAS nf_cspush
        RTS

wELSE:
        ; Layout:  ... BEQ L1 / then-body / JPA L2 / L1: else-body / L2:
        ; zTMP3/zTMP4 hold the address of the JPA operand (HERE after the
        ; opcode), which THEN patches with L2.  The false branch must skip
        ; the three-byte JPA and land on the first byte of the else body.
        LDI 0x66 JAS nf_cbyte
        LDZ zHERE SDZ zTMP3
        LDZ zHERE+1 SDZ zTMP4
        LDI 0 JAS nf_cbyte
        LDI 0 JAS nf_cbyte
        JPS nf_cspop              ; -> zT0/zT1 = IF's BEQ operand
        LDZ zT0 SDZ zPTR
        LDZ zT1 SDZ zPTR+1
        LDZ zTMP3 SDZ zT0
        LDZ zTMP4 SDZ zT1
        INCW zT0
        INCW zT0                  ; JPA operand + 2 = else body
        LDZ zT0 SDT zPTR
        INCW zPTR
        LDZ zT1 SDT zPTR
        ; Push the JPA operand address for THEN to patch.
        LDZ zTMP3 SDZ zT0
        LDZ zTMP4 SDZ zT1
        LDI 1
        JAS nf_cspush
        RTS

wTHEN:
        JPS nf_cspop
        LDZ zT0 SDZ zPTR
        LDZ zT1 SDZ zPTR+1
        LDZ zHERE SDT zPTR
        INCW zPTR
        LDZ zHERE+1 SDT zPTR
        RTS

wBEGIN:
        LDZ zHERE SDZ zT0
        LDZ zHERE+1 SDZ zT1
        LDI 2
        JAS nf_cspush
        RTS

wUNTIL:
        LDI 0x69 JAS nf_cbyte
        LDI <wIFRT JAS nf_cbyte
        LDI >wIFRT JAS nf_cbyte
        JPS nf_cspop
        LDI 0x5f JAS nf_cbyte
        LDZ zT0 JAS nf_cbyte
        LDZ zT1 JAS nf_cbyte
        RTS

wAGAIN:
        JPS nf_cspop
        LDI 0x66 JAS nf_cbyte
        LDZ zT0 JAS nf_cbyte
        LDZ zT1 JAS nf_cbyte
        RTS

wWHILE:
        LDI 0x69 JAS nf_cbyte
        LDI <wIFRT JAS nf_cbyte
        LDI >wIFRT JAS nf_cbyte
        LDI 0x5f JAS nf_cbyte
        LDZ zHERE SDZ zT0
        LDZ zHERE+1 SDZ zT1
        LDI 0 JAS nf_cbyte
        LDI 0 JAS nf_cbyte
        LDI 3
        JAS nf_cspush
        RTS

wREPEAT:
        JPS nf_cspop
        LDZ zT0 SDZ zTMP3
        LDZ zT1 SDZ zTMP4
        JPS nf_cspop
        LDI 0x66 JAS nf_cbyte
        LDZ zT0 JAS nf_cbyte
        LDZ zT1 JAS nf_cbyte
        LDZ zTMP3 SDZ zPTR
        LDZ zTMP4 SDZ zPTR+1
        LDZ zHERE SDT zPTR
        INCW zPTR
        LDZ zHERE+1 SDT zPTR
        RTS

; ---------------------------------------------------------------------------
; DO ... LOOP.
;
; Compile-time leave patches are keyed by loop: zLVD counts the loops being
; compiled, and 0x2700+zLVD holds the LEAVE count at the time DO was seen.
; That lets a nested LOOP patch only the LEAVEs that belong to it.
; ---------------------------------------------------------------------------
wDO:
        LDI 0x69 JAS nf_cbyte
        LDI <wDORUN JAS nf_cbyte
        LDI >wDORUN JAS nf_cbyte
        ; remember this loop's LEAVE base
        LDZ zLVD
        ADI <0x2700
        SDZ zPTR
        LDI >0x2700
        SDZ zPTR+1
        LDZ zLEAVE
        SDT zPTR
        INZ zLVD
        ; loop start address is HERE
        LDZ zHERE SDZ zT0
        LDZ zHERE+1 SDZ zT1
        LDI 4
        JAS nf_cspush
        RTS

wLOOP:
        ; fetch and pop this loop's LEAVE base
        DEZ zLVD
        LDZ zLVD
        ADI <0x2700
        SDZ zPTR
        LDI >0x2700
        SDZ zPTR+1
        LDT zPTR SDZ zTMP4
        JPS nf_cspop              ; -> zT0/zT1 = loop start
        ; Inline the loop test (saves the JPS/RTS round trip per iteration):
        ;   LDZ zCIDX / ADI 1 / SDZ zCIDX / LDZ zCIDX+1 / ACI 0 / SDZ zCIDX+1
        LDI 0x77 JAS nf_cbyte     ; LDZ
        LDI <zCIDX JAS nf_cbyte
        LDI 0xb0 JAS nf_cbyte     ; ADI 1
        LDI 1 JAS nf_cbyte
        LDI 0x7f JAS nf_cbyte     ; SDZ
        LDI <zCIDX JAS nf_cbyte
        LDI 0x77 JAS nf_cbyte     ; LDZ
        LDI <zCIDX+1 JAS nf_cbyte
        LDI 0xf9 JAS nf_cbyte     ; ACI 0 (propagate the low-byte carry)
        LDI 0 JAS nf_cbyte
        LDI 0x7f JAS nf_cbyte     ; SDZ
        LDI <zCIDX+1 JAS nf_cbyte
        ;   LDZ zCIDX / CPZ zCLIM / BNE start
        LDI 0x77 JAS nf_cbyte
        LDI <zCIDX JAS nf_cbyte
        LDI 0xe9 JAS nf_cbyte     ; CPZ
        LDI <zCLIM JAS nf_cbyte
        LDI 0x5e JAS nf_cbyte     ; BNE loop-start
        LDZ zT0 JAS nf_cbyte
        LDZ zT1 JAS nf_cbyte
        ;   LDZ zCIDX+1 / CPZ zCLIM+1 / BNE start
        LDI 0x77 JAS nf_cbyte
        LDI <zCIDX+1 JAS nf_cbyte
        LDI 0xe9 JAS nf_cbyte
        LDI <zCLIM+1 JAS nf_cbyte
        LDI 0x5e JAS nf_cbyte
        LDZ zT0 JAS nf_cbyte
        LDZ zT1 JAS nf_cbyte
        ; Equal: drop the loop frame, then fall through past the loop.
        LDI 0x69 JAS nf_cbyte
        LDI <nf_lpop JAS nf_cbyte
        LDI >nf_lpop JAS nf_cbyte
        JPS nf_patchleaves
        RTS

wLEAVE:
        LDI 0x69 JAS nf_cbyte
        LDI <wDROPFRAME JAS nf_cbyte
        LDI >wDROPFRAME JAS nf_cbyte
        LDI 0x66 JAS nf_cbyte     ; JPA <patched to after LOOP>
        ; record the address of the two-byte JPA operand
        LDZ zLEAVE
        SDZ zTMP
        ADZ zTMP
        ADI <zLVSTK
        SDZ zPTR
        CLZ zPTR+1
        LDZ zHERE SDT zPTR
        INCW zPTR
        LDZ zHERE+1 SDT zPTR
        INZ zLEAVE
        LDI 0 JAS nf_cbyte
        LDI 0 JAS nf_cbyte
        RTS

nf_patchleaves:                 ; patch entries zTMP4..zLEAVE-1, newest first
        LDZ zLEAVE
        CPZ zTMP4
        BEQ nfpl_done
        BCC nfpl_done
nfpl_loop:
        DEZ zLEAVE
        LDZ zLEAVE
        SDZ zTMP
        ADZ zTMP
        ADI <zLVSTK
        SDZ zPTR
        CLZ zPTR+1
        LDT zPTR SDZ zTMP2
        INCW zPTR
        LDT zPTR SDZ zTMP3
        LDZ zTMP2 SDZ zPTR
        LDZ zTMP3 SDZ zPTR+1
        LDZ zHERE SDT zPTR
        INCW zPTR
        LDZ zHERE+1 SDT zPTR
        LDZ zLEAVE
        CPZ zTMP4
        BNE nfpl_loop
nfpl_done:
        RTS

; ---------------------------------------------------------------------------
; ." : parse raw input up to the closing quote and compile it inline.
; Emits JPS wDOTQRT / length / chars.
; ---------------------------------------------------------------------------
wDOTQ:
        LDI 0x69 JAS nf_cbyte
        LDI <wDOTQRT JAS nf_cbyte
        LDI >wDOTQRT JAS nf_cbyte
nf_qbody:
        LDZ zHERE SDZ zPTR2   ; remember the length placeholder:
        LDZ zHERE+1 SDZ zPTR2+1 ; nf_cbyte clobbers zPTR
        LDI 0 JAS nf_cbyte
        CLZ zCOUNT
        LDT zIVEC
        CPI 32 BNE wq_scan
        INCW zIVEC            ; skip the delimiter after ."
wq_scan:
        LDT zIVEC
        CPI 34 BEQ wq_close
        CPI 10 BEQ wq_store
        CPI 0 BEQ wq_store
        JAS nf_cbyte
        INZ zCOUNT
        INCW zIVEC
        JPA wq_scan
wq_close:
        INCW zIVEC
wq_store:
        LDZ zCOUNT
        SDT zPTR2
        RTS

; ABORT" is compilation-only. Validate the closing quote before emitting
; anything so an incomplete string can roll back the current definition.
wABORTQ:
        LDZ zSTATE
        CPI 0
        BEQ waq_bad
        MVV zIVEC,zPTR
waq_scan:
        LDT zPTR
        CPI 34 BEQ waq_compile
        CPI 10 BEQ waq_bad
        CPI 0 BEQ waq_bad
        INCW zPTR
        JPA waq_scan
waq_compile:
        LDI 0x69 JAS nf_cbyte
        LDI <wABORTQRT JAS nf_cbyte
        LDI >wABORTQRT JAS nf_cbyte
        JPA nf_qbody
waq_bad:
        JPS _Print "ABORT quote: compile/closing quote required",10,0
        JPA nf_abort

; Runtime ( flag -- ). False skips the inline counted string; true prints
; it and abandons ALL caller frames, not just this word's return address.
wABORTQRT:
        JPS wIFRT
        BEQ waqr_skip
        LDS 2 SDZ zPTR
        LDS 1 SDZ zPTR+1
        AIV 2,zPTR
        LDT zPTR SDZ zCOUNT
        INCW zPTR
waqr_print:
        LDZ zCOUNT
        CPI 0 BEQ waqr_abort
        LDT zPTR
        JAS _PrintChar
        INCW zPTR
        DEZ zCOUNT
        JPA waqr_print
waqr_abort:
        LDI 10 JAS _PrintChar
        JPA nf_abort
waqr_skip:
        LDS 2 SDZ zPTR
        LDS 1 SDZ zPTR+1
        AIV 2,zPTR
        LDT zPTR SDZ zCOUNT
        INCW zPTR
        LDZ zCOUNT ADV zPTR
        JPA wdqr_done

; Preserve BASE, completed dictionary definitions and variable contents.
; Discard a partial colon definition, both stacks, loop/compiler state and
; the remainder of this input line. No old hardware return address is used.
nf_abort:
        LDZ zSTATE
        CPI 0 BEQ nfa_reset
        MBZ nfDefHere,zHERE
        MBZ nfDefHere+1,zHERE+1
        MBZ nfDefLatest,zLATEST
        MBZ nfDefLatest+1,zLATEST+1
nfa_reset:
        MIB 0xfe,0xffff
        MIZ 0xfe,zSP
        MIV 0x2800,zLSTKP
        CLV zLFP
        CLV zCIDX
        CLV zCLIM
        CLZ zSTATE
        CLZ zCSP
        CLZ zLVD
        CLZ zLEAVE
        JPA wRepl

wEXIT:
        LDI 0x6b JAS nf_cbyte
        RTS

wIMMEDIATE:
        LDZ zLATEST SDZ zPTR
        LDZ zLATEST+1 SDZ zPTR+1
        LDT zPTR
        ORI 0x80
        SDT zPTR
        RTS

; VARIABLE: create a word that pushes the address of a zeroed data cell.
wVARIABLE:
        JPS nf_next
        CPI 0
        BEQ nfv_done
        JPS nf_create
        LDZ zHERE
        ADI 14
        SDZ zNUM
        LDZ zHERE+1
        ACI 0
        SDZ zNUM+1
        JPS nf_clit
        LDI 0x6b JAS nf_cbyte
        LDZ zNUM SDZ zPTR
        LDZ zNUM+1 SDZ zPTR+1
        LDI 0 SDT zPTR
        INCW zPTR
        LDI 0 SDT zPTR
        LDZ zNUM
        ADI 2
        SDZ zHERE
        LDZ zNUM+1
        ACI 0
        SDZ zHERE+1
nfv_done:
        RTS

wCONSTANT:
        JPS nf_next
        CPI 0
        BEQ nfk_done
        LZP zSP,0x30 SDZ zNUM
        LZP zSP,0x31 SDZ zNUM+1
        SIZ 2,zSP
        JPS nf_create
        JPS nf_clit
        LDI 0x6b JAS nf_cbyte
nfk_done:
        RTS

wBASE:
        LIT zBASE
        RTS

wHEX:
        MIZ 16,zBASE
        CLZ zBASE+1
        RTS

wDECIMAL:
        MIZ 10,zBASE
        CLZ zBASE+1
        RTS

wHEREV:
        LIT zHERE
        RTS

; ---------------------------------------------------------------------------
; Strings and tables
; ---------------------------------------------------------------------------
primtab:
        0x03,<wDUP,>wDUP,"DUP"
        0x04,<wDROP,>wDROP,"DROP"
        0x04,<wSWAP,>wSWAP,"SWAP"
        0x04,<wOVER,>wOVER,"OVER"
        0x03,<wROT,>wROT,"ROT"
        0x03,<wNIP,>wNIP,"NIP"
        0x01,<wADD,>wADD,"+"
        0x01,<wSUB,>wSUB,"-"
        0x01,<wMUL,>wMUL,"*"
        0x01,<wDIV,>wDIV,"/"
        0x03,<wMOD,>wMOD,"MOD"
        0x03,<wAND,>wAND,"AND"
        0x02,<wOR,>wOR,"OR"
        0x03,<wXOR,>wXOR,"XOR"
        0x06,<wINV,>wINV,"INVERT"
        0x06,<wNEG,>wNEG,"NEGATE"
        0x02,<wINC,>wINC,"1+"
        0x02,<wDEC,>wDEC,"1-"
        0x02,<w2MUL,>w2MUL,"2*"
        0x02,<w2DIV,>w2DIV,"2/"
        0x01,<wEQ,>wEQ,"="
        0x02,<wNE,>wNE,"<>"
        0x01,<wLT,>wLT,"<"
        0x01,<wGT,>wGT,">"
        0x02,<wLE,>wLE,"<="
        0x02,<wGE,>wGE,">="
        0x02,<wZEQ,>wZEQ,"0="
        0x02,<wZLT,>wZLT,"0<"
        0x01,<wFETCH,>wFETCH,"@"
        0x01,<wSTORE,>wSTORE,"!"
        0x02,<wCFETCH,>wCFETCH,"C@"
        0x02,<wCSTORE,>wCSTORE,"C!"
        0x02,<wADDSTORE,>wADDSTORE,"+!"
        0x02,<wTOR,>wTOR,">R"
        0x02,<wFROMR,>wFROMR,"R>"
        0x02,<wRFETCH,>wRFETCH,"R@"
        0x07,<wEXEC,>wEXEC,"EXECUTE"
        0x04,<wEMIT,>wEMIT,"EMIT"
        0x02,<wCR,>wCR,"CR"
        0x05,<wSPACE,>wSPACE,"SPACE"
        0x04,<wTYPE,>wTYPE,"TYPE"
        0x01,<wDOT,>wDOT,"."
        0x01,<wCOLON,>wCOLON,":"
        0x81,<wSEMI,>wSEMI,";"
        0x82,<wIF,>wIF,"IF"
        0x84,<wELSE,>wELSE,"ELSE"
        0x84,<wTHEN,>wTHEN,"THEN"
        0x85,<wBEGIN,>wBEGIN,"BEGIN"
        0x85,<wUNTIL,>wUNTIL,"UNTIL"
        0x85,<wAGAIN,>wAGAIN,"AGAIN"
        0x85,<wWHILE,>wWHILE,"WHILE"
        0x86,<wREPEAT,>wREPEAT,"REPEAT"
        0x82,<wDO,>wDO,"DO"
        0x84,<wLOOP,>wLOOP,"LOOP"
        0x85,<wLEAVE,>wLEAVE,"LEAVE"
        0x01,<wI,>wI,"I"
        0x01,<wJ,>wJ,"J"
        0x06,<wDROPFRAME,>wDROPFRAME,"UNLOOP"
        0x05,<wWORDS,>wWORDS,"WORDS"
        0x82,<wDOTQ,>wDOTQ,'."'
        0x86,<wABORTQ,>wABORTQ,'ABORT"'
        0x84,<wEXIT,>wEXIT,"EXIT"
        0x89,<wIMMEDIATE,>wIMMEDIATE,"IMMEDIATE"
        0x88,<wVARIABLE,>wVARIABLE,"VARIABLE"
        0x88,<wCONSTANT,>wCONSTANT,"CONSTANT"
        0x04,<wBASE,>wBASE,"BASE"
        0x03,<wHEX,>wHEX,"HEX"
        0x07,<wDECIMAL,>wDECIMAL,"DECIMAL"
        0x04,<wHEREV,>wHEREV,"HERE"
        0x00
