#org 0x1000
start:
        LDI 0x11
        PHS
        LDI 0x22
        PHS
        PLS SDZ 0x70      ; expect 0x22
        PLS SDZ 0x71      ; expect 0x11
        LDI '1' JAS _PrintChar
        LDZ 0x70 JAS _PrintHex
        LDZ 0x71 JAS _PrintHex
        LDI ' ' JAS _PrintChar
        JPS subr
        LDI ' '
        JAS _PrintChar
        JPA _Prompt
subr:   LDI '2' JAS _PrintChar
        LDS 2 JAS _PrintHex
        LDS 1 JAS _PrintHex
        LDS 0 JAS _PrintHex
        LDI 10 JAS _PrintChar
        RTS
