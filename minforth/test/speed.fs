\ speed.min equivalent: 24 dots then END.
: speed
  83 EMIT 80 EMIT 69 EMIT 69 EMIT 68 EMIT
  32 EMIT 84 EMIT 69 EMIT 83 EMIT 84 EMIT 58 EMIT
  25 0 DO
    I 1+ 25 = IF LEAVE THEN
    46 EMIT
    50 0 DO
      50 0 DO
      LOOP
    LOOP
  LOOP
  69 EMIT 78 EMIT 68 EMIT
;
speed
