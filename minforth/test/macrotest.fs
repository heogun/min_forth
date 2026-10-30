; Data-table syntax test.
#org 0x1000

start:  LIT 0x1234
        JPA _Prompt

primtab:
        0x03,"DUP",<pDUP,>pDUP
        0x00

pDUP:   RTS
