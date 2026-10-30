"""Pin-level integration draft. Values here generate real schematic connections."""

from dataclasses import dataclass, field


NET_ALIASES = {**{f'CS_A{i}': f'A{i}' for i in range(16)},
               **{f'CS_BUS{i}': f'BUS{i}' for i in range(8)},
               'CS_CLK_MAR': 'CLK_MAR', 'CS_RESET_N': '~{RESET}',
               'CS_RI_N': '~{RI}', 'CS_RO_N': '~{RO}',
               'CS_VGA_GET_N': '~{VGA_GET}', 'CS_VREG_OE_N': '~{VREG_OE}'}


def net_name(name):
    return NET_ALIASES.get(name, name)


@dataclass
class Part:
    ref: str
    symbol: str
    value: str
    footprint: str
    sheet: str
    pins: dict = field(default_factory=dict)


def design():
    parts = []
    gates = []

    def add(ref, symbol, value, pins, sheet, footprint=None):
        if footprint is None:
            count = {'HC30': 14, 'HC04': 14, 'HC138': 16, 'HC11': 14,
                     'HC173': 16, 'HC574': 20, 'HC32': 14, 'SN76489AN': 16,
                     'HCT244': 20, 'HC283': 16, 'HC86': 14, 'HC245': 20,
                     'HC377': 20, 'HCT377': 20, 'HC74': 14, 'HC08': 14, 'HC4002': 14,
                     'HC157': 16, 'AC244': 20, 'SRAM': 28}[symbol]
            width = '15.24' if count == 28 else '7.62'
            footprint = f'Package_DIP:DIP-{count}_W{width}mm_Socket'
        p = Part(ref, symbol, value, footprint, sheet, {str(k): v for k, v in pins.items()})
        parts.append(p)
        return p

    def logic(part, op, inputs, output):
        # One entry per gate, using physical package pin numbers.
        for pin, net in inputs:
            part.pins[str(pin)] = net
        part.pins[str(output[0])] = output[1]
        gates.append({'op': op, 'inputs': [net for _, net in inputs],
                      'output': output[1], 'ref': part.ref,
                      'input_pins': [str(pin) for pin, _ in inputs], 'output_pin': str(output[0])})

    io = 'ExtensionIO'
    snd = 'PSG'
    attr = 'Attribute'
    palette = 'Palette'
    nand = add('U64', 'HC30', '74HC30', {}, io)
    logic(nand, 'NAND', list(zip([1, 2, 3, 4, 5, 6, 11, 12],
          [f'CS_A{i}' for i in range(15, 8, -1)] + ['CS_A8_N'])), (8, 'CS_FE_N'))
    inv = add('U65', 'HC04', '74HC04', {}, io)
    for a, y, source, target in [
        (1, 2, 'CS_A8', 'CS_A8_N'), (3, 4, 'CS_FE_N', 'CS_FE'),
        (5, 6, 'CS_A4', 'CS_A4_N'), (9, 8, 'CS_SN_WRITE', 'CS_SN_WRITE_N'),
        (11, 10, 'CS_AUDIO_EN', 'CS_AUDIO_MUTE'), (13, 12, 'CS_RESET_N', 'CS_RESET')]:
        logic(inv, 'NOT', [(a, source)], (y, target))
    dec = add('U66', 'HC138', '74HC138', {
        1: 'CS_A0', 2: 'CS_A1', 3: 'CS_A2', 4: 'CS_FE_N', 5: 'CS_A4',
        6: 'CS_LO', 15: 'CS_Y0_N', 14: 'CS_Y1_N', 13: 'CS_Y2_N'}, io)
    and1 = add('U67', 'HC11', '74HC11', {}, io)
    logic(and1, 'AND', [(1, 'CS_A7'), (2, 'CS_A6'), (13, 'CS_A5')], (12, 'CS_LO'))
    logic(and1, 'AND', [(3, 'CS_FE'), (4, 'CS_LO'), (5, 'CS_A4_N')], (6, 'CS_IO_HIT'))
    and2 = add('U68', 'HC11', '74HC11', {}, io)
    logic(and2, 'AND', [(1, 'CS_ATTR_MODE'), (2, 'CS_A14'), (13, 'CS_A15_N')], (12, 'CS_ATTR_CPU'))
    ctrl = add('U69', 'HC173', '74HC173', {
        1: 'GND', 2: 'GND', 3: 'CS_COLOR_EN', 4: 'CS_SN_WRITE',
        5: 'CS_ATTR_MODE', 6: 'CS_AUDIO_EN', 7: 'CS_CLK_MAR',
        9: 'CS_Y2_N', 10: 'CS_RI_N', 11: 'CS_BUS3', 12: 'CS_BUS2',
        13: 'CS_BUS1', 14: 'CS_BUS0', 15: 'CS_RESET'}, io)
    d_pins = [3, 4, 7, 8, 13, 14, 17, 18]
    q_pins = [2, 5, 6, 9, 12, 15, 16, 19]
    add('U70', 'HC377', '74HC377', {
        1: 'CS_SND_EN_N', 11: 'CS_CLK_MAR',
        **dict(zip(d_pins, [f'CS_BUS{i}' for i in range(8)])),
        **dict(zip(q_pins, [f'CS_SND{i}' for i in range(8)]))}, io)
    or1 = add('U71', 'HC32', '74HC32', {}, io)
    for inputs, output in [
        ([(1, 'CS_INH_EXT'), (2, 'CS_IO_HIT')], (3, 'CS_INH_IO')),
        ([(4, 'CS_INH_IO'), (5, 'CS_ATTR_CPU')], (6, 'CS_RAM_INH')),
        ([(9, 'CS_VGA_WE_RAW'), (10, 'CS_PENDING_ATTR')], (8, 'CS_BITMAP_WE_N')),
        ([(12, 'CS_VGA_WE_RAW'), (13, 'CS_PENDING_BITMAP')], (11, 'CS_ATTR_WE_N'))]:
        logic(or1, 'OR', inputs, output)
    or2 = add('U72', 'HC32', '74HC32', {}, io)
    logic(or2, 'OR', [(1, 'CS_Y1_N'), (2, 'CS_RO_N')], (3, 'CS_STATUS_OE_N'))
    logic(or2, 'OR', [(4, 'CS_Y0_N'), (5, 'CS_RI_N')], (6, 'CS_SND_EN_N'))
    add('U74', 'SN76489AN', 'SN76489AN', {
        # TI D0 is MSB; logical bus bit 0 goes to TI D7 (physical pin 10).
        3: 'CS_SND7', 2: 'CS_SND6', 1: 'CS_SND5', 15: 'CS_SND4',
        13: 'CS_SND3', 12: 'CS_SND2', 11: 'CS_SND1', 10: 'CS_SND0',
        4: 'CS_SN_READY', 5: 'CS_SN_WRITE_N', 6: 'CS_SN_WRITE_N',
        7: 'CS_AUDIO_RAW', 14: 'CS_SN_CLK'}, snd)
    add('U75', 'HCT244', '74HCT244', {
        1: 'CS_STATUS_OE_N', 19: 'CS_STATUS_OE_N',
        **dict(zip([2, 4, 6, 8, 11, 13, 15, 17],
                   ['CS_SN_READY', 'CS_ATTR_MODE', 'CS_COLOR_EN', 'CS_AUDIO_EN'] + ['GND'] * 4)),
        **dict(zip([18, 16, 14, 12, 9, 7, 5, 3], [f'CS_BUS{i}' for i in range(8)]))}, snd)
    add('U76', 'POR', 'MCP130-450DI/TO', {1: 'CS_RESET_N', 2: '+5V', 3: 'GND'}, snd,
        'Package_TO_SOT_THT:TO-92_Inline')
    add('X2', 'OSC', '3.579545MHz 5V FULL', {14: '+5V', 7: 'GND', 8: 'CS_SN_CLK'}, snd,
        'Oscillator:Oscillator_DIP-14')
    # The existing VREG provides address/data hold and deferred write arbitration.
    addr_pins = [10, 9, 8, 7, 6, 5, 4, 3, 25, 24, 21]
    add('U77', 'SRAM', 'AS6C62256-55PCN ATTRIBUTE', {
        **dict(zip(addr_pins, [f'CS_VA{i}' for i in range(6)] + [f'CS_CA{i}' for i in range(6, 11)])),
        1: 'GND', 2: 'GND', 23: 'GND', 26: 'GND', 20: 'GND',
        22: 'CS_VGA_GET_N', 27: 'CS_ATTR_WE_N',
        **dict(zip([11, 12, 13, 15, 16, 17, 18, 19], [f'CS_ATTR_D{i}' for i in range(8)]))}, attr)
    add('U78', 'HC283', '74HC283', {
        7: 'CS_VA8', **dict(zip([5, 3, 14, 12], [f'CS_VA{i}' for i in range(9, 13)])),
        6: 'GND', 2: 'GND', 15: 'GND', 11: 'GND',
        **dict(zip([4, 1, 13, 10], [f'CS_CA{i}' for i in range(6, 10)])),
        9: 'CS_ROW_CARRY'}, attr)
    xor = add('U79', 'HC86', '74HC86', {}, attr)
    logic(xor, 'XOR', [(1, 'CS_ROW_CARRY'), (2, 'CS_VA13')], (3, 'CS_CA10'))
    logic(xor, 'XOR', [(4, 'CS_A15'), (5, '+5V')], (6, 'CS_A15_N'))
    logic(xor, 'XOR', [(9, 'CS_ACTIVE_LATCH'), (10, '+5V')], (8, 'CS_RGB_BLANK'))
    add('U80', 'HC245', '74HC245', {
        1: '+5V', 19: 'CS_VREG_OE_N',
        **dict(zip(range(2, 10), [f'CS_VDATA{i}' for i in range(8)])),
        **dict(zip(range(18, 10, -1), [f'CS_ATTR_D{i}' for i in range(8)]))}, attr)
    add('U81', 'HCT377', '74HCT377', {
        1: 'CS_VGA_GET_N', 11: '16MHz',
        **dict(zip([3, 4, 7, 8, 13, 14, 17, 18], [f'CS_ATTR_D{i}' for i in range(8)])),
        **dict(zip([2, 5, 6, 9, 12, 15, 16, 19], [f'CS_ATTR_Q{i}' for i in range(8)]))}, attr)
    add('U82', 'HC74', '74HC74', {
        1: 'CS_RESET_N', 2: 'CS_ATTR_MODE', 3: 'CS_VREG_CP', 4: '+5V',
        5: 'CS_PENDING_ATTR', 6: 'CS_PENDING_BITMAP',
        10: '+5V', 11: 'GND', 12: 'GND', 13: 'CS_RESET_N'}, attr)
    add('U83', 'HC173', '74HC173', {
        1: 'GND', 2: 'GND', 3: 'CS_ACTIVE_LATCH', 4: 'CS_COLOR_LATCH',
        7: '16MHz', 9: 'CS_VGA_GET_N', 10: 'GND', 11: 'GND', 12: 'GND',
        13: 'CS_COLOR_EN', 14: 'CS_ACTIVE', 15: 'CS_RESET'}, palette)
    h_and = add('U84', 'HC08', '74HC08', {}, palette)
    logic(h_and, 'AND', [(1, 'CS_VA3'), (2, 'CS_VA2')], (3, 'CS_H12'))
    nor1 = add('U85', 'HC4002', '74HC4002', {}, palette)
    logic(nor1, 'NOR', list(zip([2, 3, 4, 5], [f'CS_CA{i}' for i in range(7, 11)])), (1, 'CS_VBAD'))
    logic(nor1, 'NOR', [(9, 'CS_VA5'), (10, 'CS_VA4'), (11, 'CS_H12'), (12, 'GND')], (13, 'CS_HLOW'))
    nor2 = add('U86', 'HC4002', '74HC4002', {}, palette)
    logic(nor2, 'NOR', [(2, 'CS_HHIGH_OK'), (3, 'CS_HHIGH_OK'),
                       (4, 'CS_HHIGH_OK'), (5, 'CS_HHIGH_OK')], (1, 'CS_HHIGH_BAD'))
    logic(nor2, 'NOR', [(9, 'CS_VBAD'), (10, 'CS_HLOW'),
                       (11, 'CS_HHIGH_BAD'), (12, 'CS_V256')], (13, 'CS_ACTIVE'))
    h_nand = add('U87', 'HC30', '74HC30', {}, palette)
    logic(h_nand, 'NAND', list(zip([1, 2, 3, 4, 5, 6, 11, 12],
          [f'CS_VA{i}' for i in range(5, 0, -1)] + ['+5V'] * 3)), (8, 'CS_HHIGH_OK'))
    mux_in0 = [2, 5, 11, 14]
    mux_in1 = [3, 6, 10, 13]
    mux_out = [4, 7, 9, 12]
    add('U88', 'HC157', '74HC157', {1: 'CS_PIXEL', 15: 'GND',
        **dict(zip(mux_in0, [f'CS_ATTR_Q{i}' for i in range(4, 8)])),
        **dict(zip(mux_in1, [f'CS_ATTR_Q{i}' for i in range(4)])),
        **dict(zip(mux_out, [f'CS_COLOR{i}' for i in range(4)]))}, palette)
    add('U89', 'HC157', '74HC157', {1: 'CS_COLOR_LATCH', 15: 'GND',
        **dict(zip(mux_in0, ['CS_PIXEL'] * 4)),
        **dict(zip(mux_in1, [f'CS_COLOR{i}' for i in range(4)])),
        **dict(zip(mux_out, ['CS_B', 'CS_G', 'CS_R', 'CS_I']))}, palette)
    add('U90', 'AC244', '74AC244', {1: 'CS_RGB_BLANK', 19: 'CS_RGB_BLANK',
        **dict(zip([2, 4, 6, 8, 11, 13, 15, 17],
                   ['CS_R', 'CS_I', 'CS_G', 'CS_I', 'CS_B', 'CS_I', 'GND', 'GND'])),
        **dict(zip([18, 16, 14, 12, 9, 7],
                   ['CS_DAC_R', 'CS_DAC_RI', 'CS_DAC_G', 'CS_DAC_GI', 'CS_DAC_B', 'CS_DAC_BI']))}, palette)

    def resistor(ref, value, a, b, sheet):
        return add(ref, 'R', value, {1: a, 2: b}, sheet,
                   'Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal')
    # Existing R6 becomes the red 750-ohm DAC resistor on the VGA sheet.
    for ref, value, a, b in [
        ('R28', '750', 'CS_DAC_G', 'CS_VGA_G'), ('R29', '750', 'CS_DAC_B', 'CS_VGA_B'),
        ('R30', '1.5k', 'CS_DAC_RI', 'CS_VGA_R'), ('R31', '1.5k', 'CS_DAC_GI', 'CS_VGA_G'),
        ('R32', '1.5k', 'CS_DAC_BI', 'CS_VGA_B')]:
        resistor(ref, value, a, b, palette)
    resistor('R33', '4.7k', '+5V', 'CS_SN_READY', snd)
    resistor('R34', '1k', 'CS_AUDIO_AC', 'CS_LINE_OUT', snd)
    resistor('R35', '10k', 'CS_LINE_OUT', 'GND', snd)
    resistor('R36', '100k', '+5V', 'CS_AUDIO_MUTE', snd)
    add('Q1', '2N7000', '2N7000', {1: 'GND', 2: 'CS_AUDIO_MUTE', 3: 'CS_LINE_OUT'}, snd,
        'Package_TO_SOT_THT:TO-92_Inline')
    add('J6', 'CONN2', 'MONO LINE OUT / EXTERNAL AMP', {1: 'CS_LINE_OUT', 2: 'GND'}, snd,
        'Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical')
    add('C62', 'C', '220n', {1: 'CS_AUDIO_RAW', 2: 'CS_AUDIO_AC'}, snd,
        'Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P2.50mm')
    # One local ceramic per IC, including the supervisor; separate bulk storage.
    for p in [p for p in parts if p.ref.startswith('U')]:
        add(f'C{34+int(p.ref[1:])-64}', 'C', '100n', {1: '+5V', 2: 'GND'}, 'ExtensionPower',
            'Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P2.50mm')
    add('C61', 'CP', '10u 16V', {1: '+5V', 2: 'GND'}, 'ExtensionPower',
        'Capacitor_THT:CP_Radial_D5.0mm_P2.50mm')
    add('C63', 'C', '100n', {1: '+5V', 2: 'GND'}, 'ExtensionPower',
        'Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P2.50mm')
    for p in parts:
        p.pins = {pin: net_name(net) for pin, net in p.pins.items()}
    for gate in gates:
        gate['inputs'] = [net_name(n) for n in gate['inputs']]
        gate['output'] = net_name(gate['output'])
    return parts, gates


SOURCES = {
    **{f'CS_A{i}': ('RAM.kicad_sch', f'U{27 if i < 4 else 29 if i < 8 else 30 if i < 12 else 32}',
                    str([14, 13, 12, 11][i % 4])) for i in range(16)},
    **{f'CS_BUS{i}': ('VGA.kicad_sch', 'U38', str([5, 9, 4, 8, 3, 7, 2, 6][i])) for i in range(8)},
    **{f'CS_VA{i}': ('VGA.kicad_sch', 'U40' if i < 8 else 'U41',
                     str([19, 18, 17, 16, 15, 14, 13, 12][i % 8])) for i in range(14)},
    **{f'CS_VDATA{i}': ('VGA.kicad_sch', 'U38', str([16, 12, 17, 13, 18, 14, 19, 15][i])) for i in range(8)},
    'CS_VREG_CP': ('VGA.kicad_sch', 'U38', '11'),
    'CS_VGA_GET_N': ('VGA.kicad_sch', 'U35', '15'),
    'CS_VREG_OE_N': ('VGA.kicad_sch', 'U38', '1'),
    'CS_V256': ('VGA.kicad_sch', 'U39', '7'),
    'CS_CLK_MAR': ('RAM.kicad_sch', 'J3', '6'),
    'CS_RI_N': ('RAM.kicad_sch', 'J3', '32'),
    'CS_RO_N': ('RAM.kicad_sch', 'J3', '31'),
    'CS_RESET_N': ('RAM.kicad_sch', 'J3', '5'),
}
