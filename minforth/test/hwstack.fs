#org 0x1000
start:  JPS subr
        JPA start
subr:   LDI 'S' JAS _PrintChar
        LDS 0 JAS _PrintHex
        LDS 1 JAS _PrintHex
        LDS 2 JAS _PrintHex
        LDS 3 JAS _PrintHex
        LDS 4 JAS _PrintHex
        LDS 5 JAS _PrintHex
        LDI '=' JAS _PrintChar
        LDI <after JAS _PrintHex
        LDI >after JAS _PrintHex
        LDI 10 JAS _PrintChar
        JPA subr
after:  0
