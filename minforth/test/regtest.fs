#org 0x1000
start:  LDI 0x41          ; 'A'
        JPS targ1         ; A afterwards?
        JAS _PrintChar    ; print it
        LDI 0x42          ; 'B'
        JAS targ2         ; A afterwards?
        JAS _PrintChar
        LDI 10
        JAS _PrintChar
        JPA _Prompt
targ1:  RTS
targ2:  RTS
