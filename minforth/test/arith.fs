; Probe: 16-bit add/sub with carry through LZP/SZP.
#org 0x1000

start:  MIB 0xfe,0xffff          ; hardware stack
        MIZ 0xfe,zSP             ; empty data stack

        ; --- add 0x12ff + 0x3401 ---
        LIT 0x12ff
        LIT 0x3401                ; SP now 2, NP=0
        SETNP
        JPS padd
        SETSPNP
        JPS pnum
        LDI ' ' JAS _PrintChar

        ; --- sub 0x4700 - 0x3401 = 0x12ff ---
        MIZ 0xfe,zSP
        LIT 0x4700
        LIT 0x3401
        SETNP
        JPS psub
        SETSPNP
        JPS pnum
        LDI 10 JAS _PrintChar
        JPA _Prompt

; print top cell as 4 hex digits
pnum:   LZP zSP,0x21 JAS _PrintHex
        LZP zSP,0x20 JAS _PrintHex
        RTS

; a b -- a+b  (does not drop b)
padd:   LZP zSP,0x20 SDZ zT0
        LZP zSP,0x21 SDZ zT1
        LZP zNP,0x20
        ADZ zT0
        SZP zNP,0x20
        LZP zNP,0x21
        ACZ zT1
        SZP zNP,0x21
        RTS

; a b -- a-b
psub:   LZP zSP,0x20 SDZ zT0
        LZP zSP,0x21 SDZ zT1
        LZP zNP,0x20
        SUZ zT0
        SZP zNP,0x20
        LZP zNP,0x21
        SCZ zT1
        SZP zNP,0x21
        RTS
