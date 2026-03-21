"""MCP prompt templates for common electronic circuit designs.

Extensive set of 16 templates covering analog, digital, power, RF, and sensor circuits.
Each prompt provides structured guidance for Claude to build the circuit using SKiDL tools.
"""

from __future__ import annotations


PROMPTS = {
    # ── Analog ──────────────────────────────────────────────────────────────

    "design_voltage_divider": {
        "description": "Design a resistive voltage divider circuit with ratio calculation",
        "arguments": [
            {"name": "v_in", "description": "Input voltage (e.g. '12')", "required": True},
            {"name": "v_out", "description": "Desired output voltage (e.g. '3.3')", "required": True},
            {"name": "current_ma", "description": "Desired divider current in mA (e.g. '1')", "required": False},
        ],
        "template": """Design a resistive voltage divider circuit using SKiDL.

Requirements:
- Input voltage: {v_in}V
- Desired output voltage: {v_out}V
- Divider current: {current_ma}mA (if specified)

Steps:
1. Calculate R1 and R2 values using: Vout = Vin * R2/(R1+R2)
2. Select nearest standard resistor values (E24 series)
3. Create a circuit with create_circuit()
4. Add two resistors from the "Device" library with appropriate values and 0805 footprints
5. Create VIN, VOUT, and GND nets
6. Connect R1 between VIN and VOUT, R2 between VOUT and GND
7. Run ERC and generate schematic

Consider: power dissipation, tolerance effects on output accuracy, loading effects.""",
    },

    "design_amplifier": {
        "description": "Design a non-inverting or inverting op-amp amplifier circuit",
        "arguments": [
            {"name": "topology", "description": "Amplifier type: 'inverting' or 'non_inverting'", "required": True},
            {"name": "gain", "description": "Desired voltage gain (e.g. '10')", "required": True},
            {"name": "opamp", "description": "Op-amp part number (e.g. 'LM358', 'OPA2134')", "required": False},
        ],
        "template": """Design an op-amp amplifier circuit using SKiDL.

Requirements:
- Topology: {topology}
- Desired gain: {gain}x
- Op-amp: {opamp} (or suggest a suitable general-purpose op-amp)

Steps:
1. Calculate feedback resistor values:
   - Non-inverting: Gain = 1 + Rf/Rg
   - Inverting: Gain = -Rf/Rin
2. Select standard resistor values
3. Create circuit and add: op-amp, Rf (feedback resistor), Rg/Rin (gain-setting resistor)
4. Add bypass capacitors (100nF) on power pins
5. Create nets: VIN, VOUT, V+, V-, GND
6. Wire the circuit according to the topology
7. Run ERC and generate schematic

Consider: input/output impedance, bandwidth (GBW product), power supply requirements, input bias current effects.""",
    },

    "design_filter": {
        "description": "Design an active low-pass, high-pass, or band-pass filter",
        "arguments": [
            {"name": "filter_type", "description": "Filter type: 'lowpass', 'highpass', or 'bandpass'", "required": True},
            {"name": "cutoff_hz", "description": "Cutoff frequency in Hz (e.g. '1000')", "required": True},
            {"name": "order", "description": "Filter order: '1' or '2' (Sallen-Key)", "required": False},
        ],
        "template": """Design an active {filter_type} filter using SKiDL.

Requirements:
- Filter type: {filter_type}
- Cutoff frequency: {cutoff_hz} Hz
- Order: {order} (1st order or 2nd order Sallen-Key)

Steps:
1. Calculate component values:
   - 1st order: fc = 1/(2*pi*R*C)
   - 2nd order Sallen-Key: use equal-component design
2. Select standard R and C values
3. Create circuit with op-amp, resistors, and capacitors
4. Add power supply bypass capacitors
5. Wire according to filter topology
6. Run ERC and generate schematic

Consider: Q factor (for 2nd order), passband gain, component tolerance sensitivity, op-amp GBW requirements.""",
    },

    "design_oscillator": {
        "description": "Design a 555 timer or crystal oscillator circuit",
        "arguments": [
            {"name": "osc_type", "description": "Oscillator type: '555_astable', '555_monostable', or 'crystal'", "required": True},
            {"name": "frequency_hz", "description": "Desired frequency in Hz (e.g. '1000' for 555, '16000000' for crystal)", "required": True},
        ],
        "template": """Design a {osc_type} oscillator circuit using SKiDL.

Requirements:
- Type: {osc_type}
- Frequency: {frequency_hz} Hz

Steps for 555 astable:
1. Calculate R1, R2, C values: f = 1.44/((R1+2*R2)*C)
2. Add 555 timer IC, resistors, capacitors, bypass cap
3. Wire: VCC to pin 8, GND to pin 1, R1 from VCC to pin 7, R2 from pin 7 to pins 2&6, C from pins 2&6 to GND
4. Pin 4 (Reset) to VCC, Pin 5 (Control) via 10nF to GND

Steps for crystal oscillator:
1. Select crystal and load capacitors (C_load specified in crystal datasheet)
2. Calculate load caps: C1 = C2 = 2*C_load - C_stray (typically 5pF stray)
3. Add crystal, two load caps, feedback resistor (1M)
4. Wire Pierce oscillator topology

Run ERC and generate schematic.""",
    },

    # ── Power ───────────────────────────────────────────────────────────────

    "design_power_supply": {
        "description": "Design a linear or switching voltage regulator circuit",
        "arguments": [
            {"name": "regulator_type", "description": "Type: 'linear' (LDO) or 'switching' (buck/boost)", "required": True},
            {"name": "v_in", "description": "Input voltage (e.g. '12')", "required": True},
            {"name": "v_out", "description": "Output voltage (e.g. '3.3')", "required": True},
            {"name": "current_ma", "description": "Max output current in mA (e.g. '500')", "required": True},
        ],
        "template": """Design a {regulator_type} voltage regulator circuit using SKiDL.

Requirements:
- Type: {regulator_type}
- Input: {v_in}V → Output: {v_out}V
- Max current: {current_ma}mA

For linear (LDO) regulator:
1. Select appropriate LDO (e.g. AMS1117-3.3, LM7805, MCP1700)
2. Add input cap (10µF), output cap (10µF), and optional 100nF ceramic bypass
3. Wire: VIN→input cap→regulator IN, regulator OUT→output cap→VOUT, GND connections

For switching (buck) regulator:
1. Select buck converter IC (e.g. LM2596, MP1584)
2. Add inductor (calculate L based on ripple requirements)
3. Add input/output caps, feedback resistors, bootstrap cap, Schottky diode
4. Wire per datasheet reference design

Run ERC, validate footprints, generate schematic and BOM.""",
    },

    "design_led_circuit": {
        "description": "Design an LED driver circuit with current limiting",
        "arguments": [
            {"name": "led_color", "description": "LED color: 'red', 'green', 'blue', 'white'", "required": True},
            {"name": "v_supply", "description": "Supply voltage (e.g. '5', '3.3')", "required": True},
            {"name": "num_leds", "description": "Number of LEDs (series or parallel)", "required": False},
            {"name": "current_ma", "description": "LED current in mA (default: 20)", "required": False},
        ],
        "template": """Design an LED driver circuit using SKiDL.

Requirements:
- LED color: {led_color} (Vf: red≈1.8V, green≈2.2V, blue/white≈3.0V)
- Supply voltage: {v_supply}V
- Number of LEDs: {num_leds} (default: 1)
- LED current: {current_ma}mA (default: 20mA)

Steps:
1. Calculate current-limiting resistor: R = (Vsupply - Vf) / I_led
2. Select nearest standard resistor value (round up for safety)
3. Verify power dissipation: P_R = I² × R (ensure < 1/4W for 0805)
4. Create circuit with LED(s) from Device library and resistor(s)
5. For multiple LEDs: series (higher voltage needed) or parallel (individual resistors)
6. Wire: VCC → R → LED anode, LED cathode → GND
7. Run ERC and generate schematic

Consider: thermal derating, forward voltage tolerance, dimming options (PWM-capable pin).""",
    },

    "design_battery_charger": {
        "description": "Design a Li-ion/LiPo battery charging circuit",
        "arguments": [
            {"name": "chemistry", "description": "Battery chemistry: 'li_ion' or 'lipo'", "required": True},
            {"name": "capacity_mah", "description": "Battery capacity in mAh (e.g. '2000')", "required": True},
            {"name": "charge_current_ma", "description": "Charge current in mA (default: C/2 rate)", "required": False},
        ],
        "template": """Design a {chemistry} battery charger circuit using SKiDL.

Requirements:
- Chemistry: {chemistry} (4.2V per cell)
- Battery capacity: {capacity_mah}mAh
- Charge current: {charge_current_ma}mA (default: C/2 = {capacity_mah}/2 mA)

Steps:
1. Select charger IC (e.g. MCP73831 for single cell, TP4056 module)
2. Calculate programming resistor for charge current: Rprog per datasheet
3. Add components: charger IC, input cap, charge status LED(s), programming resistor
4. Add reverse polarity protection (optional: Schottky diode or P-MOSFET)
5. Wire per datasheet reference design
6. Add USB or barrel jack input connector

Run ERC, validate footprints, generate schematic and BOM.

Consider: thermal management, pre-charge/termination currents, battery protection (over-discharge, overcurrent).""",
    },

    # ── Digital ─────────────────────────────────────────────────────────────

    "design_microcontroller": {
        "description": "Design a microcontroller circuit with essential support components",
        "arguments": [
            {"name": "mcu", "description": "MCU part (e.g. 'ATmega328P-AU', 'STM32F103C8T6', 'ESP32-WROOM-32')", "required": True},
            {"name": "clock_mhz", "description": "Clock frequency in MHz (e.g. '16')", "required": False},
            {"name": "interfaces", "description": "Comma-separated interfaces to break out: 'uart,spi,i2c,gpio'", "required": False},
        ],
        "template": """Design a microcontroller circuit with support components using SKiDL.

Requirements:
- MCU: {mcu}
- Clock: {clock_mhz}MHz (if external crystal needed)
- Interfaces: {interfaces}

Essential support components:
1. Power supply decoupling:
   - 100nF ceramic cap on each VCC/VDD pin (as close as possible)
   - 10µF bulk cap near power input
2. Reset circuit:
   - 10k pull-up resistor to VCC
   - 100nF cap to GND (for noise filtering)
   - Optional reset button (tactile switch to GND)
3. Crystal/oscillator (if needed):
   - Crystal with load capacitors
   - See design_oscillator template for values
4. Programming header:
   - ISP/SWD/JTAG connector per MCU family
5. Status LED on a GPIO pin

Wire all power pins, add all decoupling caps, connect crystal, break out requested interfaces to headers.

Run ERC, validate footprints, generate schematic and BOM.""",
    },

    "design_logic_level_shifter": {
        "description": "Design a voltage level translation circuit",
        "arguments": [
            {"name": "v_low", "description": "Low-side voltage (e.g. '3.3')", "required": True},
            {"name": "v_high", "description": "High-side voltage (e.g. '5')", "required": True},
            {"name": "channels", "description": "Number of channels (e.g. '4')", "required": True},
            {"name": "direction", "description": "Direction: 'unidirectional' or 'bidirectional'", "required": False},
        ],
        "template": """Design a logic level shifter circuit using SKiDL.

Requirements:
- Low side: {v_low}V
- High side: {v_high}V
- Channels: {channels}
- Direction: {direction}

Options:
A) MOSFET-based bidirectional (for I2C, open-drain):
   - BSS138 N-MOSFET per channel
   - Pull-up resistors on both sides (4.7k-10k)
   - Wire: gate to V_low, source to low-side signal, drain to high-side signal

B) Dedicated IC (simpler for many channels):
   - TXB0104 (bidirectional, 4-channel)
   - 74LVC245 (unidirectional, 8-channel)
   - Add bypass caps on both voltage rails

C) Resistor divider (unidirectional high→low only):
   - Two resistors per channel forming voltage divider

Select the appropriate approach and build the circuit.
Run ERC and generate schematic.""",
    },

    "design_i2c_bus": {
        "description": "Design an I2C bus with pull-ups and multiple device connections",
        "arguments": [
            {"name": "voltage", "description": "Bus voltage (e.g. '3.3' or '5')", "required": True},
            {"name": "devices", "description": "Comma-separated I2C devices (e.g. 'EEPROM,temp_sensor,RTC')", "required": True},
            {"name": "speed", "description": "Bus speed: 'standard' (100kHz), 'fast' (400kHz), 'fast_plus' (1MHz)", "required": False},
        ],
        "template": """Design an I2C bus circuit using SKiDL.

Requirements:
- Bus voltage: {voltage}V
- Devices: {devices}
- Speed: {speed} (affects pull-up values)

Steps:
1. Calculate pull-up resistor values:
   - Standard (100kHz): 4.7kΩ typical
   - Fast (400kHz): 2.2kΩ typical
   - Fast+ (1MHz): 1kΩ typical
   - Consider: R_pullup > V_bus / 3mA (I2C sink current limit)
2. Create SDA and SCL nets
3. Add pull-up resistors from SDA→VCC and SCL→VCC
4. Add each I2C device with its required support components
5. Add 100nF decoupling cap per device
6. Connect all devices' SDA pins to SDA net, SCL to SCL net
7. Add test points on SDA and SCL for debugging

Run ERC and generate schematic.""",
    },

    "design_spi_bus": {
        "description": "Design an SPI bus with chip selects for multiple peripherals",
        "arguments": [
            {"name": "voltage", "description": "Bus voltage (e.g. '3.3')", "required": True},
            {"name": "num_devices", "description": "Number of SPI slave devices", "required": True},
            {"name": "devices", "description": "Comma-separated device types (e.g. 'flash,display,ADC')", "required": False},
        ],
        "template": """Design an SPI bus circuit using SKiDL.

Requirements:
- Bus voltage: {voltage}V
- Number of slave devices: {num_devices}
- Devices: {devices}

Steps:
1. Create shared SPI nets: MOSI, MISO, SCK
2. Create individual CS (chip select) nets: CS0, CS1, ..., CS{num_devices}
3. Add pull-up resistors (10k) on each CS line (active low)
4. For each slave device:
   - Add the device IC
   - Add 100nF decoupling cap
   - Connect MOSI, MISO, SCK to shared bus
   - Connect individual CS line
5. Consider series resistors (33-100Ω) on MOSI/MISO/SCK for signal integrity
6. Add test points for debugging

Run ERC and generate schematic.

Consider: signal integrity at high speeds, CS timing, MISO tri-state behavior.""",
    },

    # ── Sensor/Interface ────────────────────────────────────────────────────

    "design_sensor_interface": {
        "description": "Design an analog sensor input with signal conditioning for ADC",
        "arguments": [
            {"name": "sensor_type", "description": "Sensor type: 'thermistor', 'photodiode', 'strain_gauge', 'voltage'", "required": True},
            {"name": "adc_voltage", "description": "ADC reference voltage (e.g. '3.3')", "required": True},
            {"name": "sensor_range", "description": "Sensor output range (e.g. '0-5V', '0-100mV', '10k-100k ohm')", "required": False},
        ],
        "template": """Design an analog sensor interface with signal conditioning using SKiDL.

Requirements:
- Sensor type: {sensor_type}
- ADC reference voltage: {adc_voltage}V
- Sensor range: {sensor_range}

For thermistor (NTC):
1. Voltage divider with reference resistor (equal to R_25°C)
2. Optional: linearization network for improved accuracy
3. Filter cap (100nF) at ADC input

For voltage input:
1. Resistive divider to scale to ADC range
2. Op-amp buffer for high-impedance inputs
3. Anti-aliasing RC filter (fc = 10× sample rate)
4. TVS/Zener clamping diode for protection

For strain gauge:
1. Wheatstone bridge excitation
2. Instrumentation amplifier (e.g. INA128)
3. Low-pass filter
4. Reference voltage for bridge

Add ESD protection at connector/input, RC filter before ADC, and decoupling caps.
Run ERC and generate schematic.""",
    },

    "design_motor_driver": {
        "description": "Design an H-bridge or MOSFET motor driver circuit",
        "arguments": [
            {"name": "motor_type", "description": "Motor type: 'dc_brushed', 'stepper', 'servo'", "required": True},
            {"name": "voltage", "description": "Motor supply voltage (e.g. '12')", "required": True},
            {"name": "current_a", "description": "Motor max current in amps (e.g. '2')", "required": True},
        ],
        "template": """Design a motor driver circuit using SKiDL.

Requirements:
- Motor type: {motor_type}
- Supply voltage: {voltage}V
- Max current: {current_a}A

For DC brushed motor (H-bridge):
1. Select driver IC based on voltage/current:
   - <1A: L293D, DRV8833
   - 1-3A: L298N, DRV8871
   - >3A: Discrete MOSFET H-bridge (IRF540N + IRF9540N)
2. Add bulk decoupling caps (100µF electrolytic + 100nF ceramic)
3. Add flyback diodes (if not integrated): 1N4007 or Schottky
4. Wire: motor power, control inputs (PWM, DIR), enable
5. Add current sense resistor (optional, for feedback)

For stepper motor:
1. Select stepper driver (A4988, DRV8825, TMC2209)
2. Wire STEP, DIR, ENABLE pins
3. Add current-setting resistor per datasheet
4. Add decoupling on motor supply and logic supply

Run ERC, validate footprints, generate schematic and BOM.""",
    },

    "design_uart_interface": {
        "description": "Design a UART/RS-232 or UART/USB level converter interface",
        "arguments": [
            {"name": "interface_type", "description": "Interface: 'rs232' or 'usb_serial'", "required": True},
            {"name": "logic_voltage", "description": "MCU logic voltage (e.g. '3.3' or '5')", "required": True},
        ],
        "template": """Design a {interface_type} UART interface using SKiDL.

Requirements:
- Interface type: {interface_type}
- Logic voltage: {logic_voltage}V

For RS-232:
1. Select MAX232 (5V) or MAX3232 (3.3V) level converter
2. Add charge pump capacitors (4× 100nF for MAX232, 4× 100nF for MAX3232)
3. Add DB9 connector
4. Wire: TX_TTL → T_IN → T_OUT → DB9, DB9 → R_IN → R_OUT → RX_TTL
5. Add ESD protection on DB9 connector lines

For USB-Serial:
1. Select USB-UART bridge IC (FT232RL, CH340G, CP2102)
2. Add USB Type-B/Micro-B/C connector
3. Add 27Ω series resistors on D+/D- (if not integrated)
4. Add ESD protection (USBLC6-2)
5. Add decoupling caps, ferrite bead on USB power
6. Optional: add TX/RX LEDs

Run ERC and generate schematic.""",
    },

    "design_usb_interface": {
        "description": "Design a USB connector interface with ESD protection",
        "arguments": [
            {"name": "usb_type", "description": "Connector: 'type_a', 'type_b', 'micro_b', 'type_c'", "required": True},
            {"name": "function", "description": "Function: 'power_only', 'data', 'otg'", "required": True},
            {"name": "voltage", "description": "Logic voltage for data lines (e.g. '3.3')", "required": False},
        ],
        "template": """Design a USB {usb_type} interface circuit using SKiDL.

Requirements:
- Connector type: {usb_type}
- Function: {function}
- Data logic voltage: {voltage}V

Steps:
1. Add USB connector from Connector library
2. For Type-C: add CC resistors (5.1kΩ to GND for UFP/sink)
3. Add ESD protection IC (USBLC6-2SC6 or TPD2E2U06)
4. Add ferrite bead on VBUS for noise filtering
5. For data function:
   - 27Ω series resistors on D+/D- (USB 2.0 FS)
   - 1.5kΩ pull-up on D+ (for device mode, full speed)
6. Add bulk cap on VBUS (10µF + 100nF)
7. Optional: VBUS power switch IC for host mode

Run ERC, validate footprints, generate schematic and BOM.

Consider: USB spec compliance, impedance matching for high-speed, shield grounding.""",
    },

    # ── RF ──────────────────────────────────────────────────────────────────

    "design_antenna_matching": {
        "description": "Design an impedance matching network for RF antenna",
        "arguments": [
            {"name": "frequency_mhz", "description": "Operating frequency in MHz (e.g. '433', '915', '2400')", "required": True},
            {"name": "z_source", "description": "Source impedance in ohms (e.g. '50')", "required": True},
            {"name": "topology", "description": "Matching network: 'pi', 'L', 'T'", "required": False},
        ],
        "template": """Design an RF impedance matching network using SKiDL.

Requirements:
- Frequency: {frequency_mhz} MHz
- Source impedance: {z_source}Ω
- Matching topology: {topology}

Steps:
1. Calculate matching component values using Smith chart or equations:
   - L-match: two reactive elements (L+C or C+L)
   - Pi-match: C-L-C (common for PA output)
   - T-match: L-C-L
2. Select standard inductor and capacitor values (from E12 series)
3. Use high-Q RF-rated components (NP0/C0G capacitors, air-core/chip inductors)
4. Create circuit with matching components
5. Add SMA or u.FL connector for antenna port
6. Add GND stitching vias (note in BOM/comments)

Run ERC and generate schematic.

Consider: component Q factor, self-resonant frequency (SRF > 2× operating frequency),
PCB layout parasitics, ground plane requirements.""",
    },
}


def get_prompt(name: str, **kwargs) -> str:
    """Render a prompt template with the given arguments."""
    if name not in PROMPTS:
        available = list(PROMPTS.keys())
        raise KeyError(f"Prompt '{name}' not found. Available: {available}")

    prompt_def = PROMPTS[name]
    template = prompt_def["template"]

    # Fill in provided arguments, leave placeholders for missing optional ones
    for arg in prompt_def.get("arguments", []):
        arg_name = arg["name"]
        if arg_name in kwargs:
            template = template.replace("{" + arg_name + "}", str(kwargs[arg_name]))
        elif not arg.get("required", False):
            template = template.replace("{" + arg_name + "}", f"(not specified)")

    return template


def list_prompts() -> list[dict]:
    """List all available prompt templates."""
    result = []
    for name, prompt_def in PROMPTS.items():
        result.append({
            "name": name,
            "description": prompt_def["description"],
            "arguments": prompt_def.get("arguments", []),
        })
    return result
