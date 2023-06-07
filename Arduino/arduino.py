#!/usr/bin/env python
import logging
import itertools
import platform
import serial
import time
from serial.tools import list_ports

import sys
if sys.platform.startswith('win'):
    import winreg
else:
    import glob

libraryVersion = 'V0.6'

log = logging.getLogger(__name__)


def enumerate_serial_ports():
    """
    Uses the Win32 registry to return a iterator of serial
        (COM) ports existing on this computer.
    """
    path = 'HARDWARE\\DEVICEMAP\\SERIALCOMM'
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
    except OSError:
        raise Exception

    for i in itertools.count():
        try:
            val = winreg.EnumValue(key, i)
            yield (str(val[1]))  # , str(val[0]))
        except EnvironmentError:
            break
def rd(sr):
    """
    Serial read
    -------------
    reads line from serial, removes carriage returns and newlines
    """
    t = sr.readline().decode("utf-8").replace("\r\n", "")
    return t

def write_and_flush(sr, data, raise_error=False):
    """
    Writes and flushes
    -------------
    inputs:
        data : cmd_string
    """
    try:
        sr.write(data)
        sr.flush()
    except BaseException as e:
        if raise_error:
            print(f'data = {data}')
            raise e
        pass

def build_cmd_str(cmd, args=None):
    """
    Build a command string that can be sent to the arduino.

    Input:
        cmd (str): the command to send to the arduino, must not
            contain a '@', '%', '!', or '$' character
        args (iterable): the arguments to send to the command

    @TODO: a strategy is needed to escape % characters in the args
    @TODO: a method of creating checksum is needed (preferably with ECC)
    """
    cmd = str(cmd)
    if args:
        args = '%'.join(map(str, args))
    else:
        args = ''
    return f"@{cmd}%{args}$!"


def find_port(baud, timeout):
    """
    Find the first port that is connected to an arduino with a compatible
    sketch installed.
    """
    baud = int(baud)
    timeout = int(timeout)
    if platform.system() == 'Windows':
        ports = enumerate_serial_ports()
    elif platform.system() == 'Darwin':
        ports = [i[0] for i in list_ports.comports()]
        ports = ports[::-1]
    else:
        ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    for port in ports:
        log.debug(f'Found {port}, testing...')
        try:
            sr = serial.Serial(port, baud, timeout=timeout)
        except (serial.serialutil.SerialException, OSError) as e:
            log.debug(str(e))
            continue

        sr.readline() # wait for board to start up again

        version = get_version(sr)

        if version != libraryVersion:
            try:
                ver = version[0]
            except Exception:
                ver = ''

            if ver == 'V' or version == "version":
                print("You need to update the version of the Arduino-Python3",
                      "library running on your Arduino.")
                print("The Arduino sketch is", version)
                print("The Python installation is", libraryVersion)
                print("Flash the prototype sketch again.")
                return sr

            # established to be the wrong board
            log.debug(f'Bad version {version}. This is not a Shrimp/Arduino!')
            sr.close()
            continue

        log.info(f'Using port {port}.')
        if sr:
            return sr
    return None

def get_version(sr):
    cmd_str = build_cmd_str("version")
    try:
        sr.write(str.encode(cmd_str))
        sr.flush()
    except Exception:
        return None
    return sr.readline().decode("utf-8").replace("\r\n", "")


class Arduino(object):


    def __init__(self, baud=115200, port=None, timeout=2, sr=None):
        """
        Initializes serial communication with Arduino if no connection is
        given. Attempts to self-select COM port, if not specified.
        """
        if not sr:
            if not port:
                sr = find_port(baud, timeout)
                if not sr:
                    raise ValueError("Could not find port.")
            else:
                sr = serial.Serial(port, baud, timeout=timeout)
                sr.readline() # wait til board has rebooted and is connected

                version = get_version(sr)

                if version != libraryVersion:
                    # check version
                    try:
                        ver = version[0]
                    except Exception:
                        ver = ''

                    if ver == 'V' or version == "version":
                        print("You need to update the version of the Arduino-Python3",
                              "library running on your Arduino.")
                        print("The Arduino sketch is", version)
                        print("The Python installation is", libraryVersion)
                        print("Flash the prototype sketch again.")

        sr.flush()
        self.sr = sr
        self.SoftwareSerial = SoftwareSerial(self)
        self.Servos = Servos(self)
        self.EEPROM = EEPROM(self)
        self.pinModeDic = {}

    def version(self):
        return get_version(self.sr)

    def digitalWrite(self, pin, val):
        """
        Sends digitalWrite command
        to digital pin on Arduino
        -------------
        inputs:
           pin : digital pin number
           val : either "HIGH" or "LOW"
        """
        pin = int(pin)
        val = str(val).upper()
        valid = ('HIGH','LOW')
        if not self.pinModeDic[pin] == 'OUTPUT':
            raise ValueError('pin: {} not set to OUTPUT'.format(pin))
        if val in valid:
            if val == "LOW":
                pin_ = -pin
            else:
                pin_ = pin
            cmd_str = build_cmd_str("dw", (pin_,))
            write_and_flush(self.sr,cmd_str)
        else:
            raise ValueError('val: {} not in {}'.format(str(val).upper(), str(valid)))

    def analogWrite(self, pin, val):
        """
        Sends analogWrite pwm command
        to pin on Arduino
        -------------
        inputs:
           pin : pin number
           val : integer 0 (off) to 255 (always on)
        """
        pin = int(pin)
        val = int(val)
        if not self.pinModeDic[pin] == 'OUTPUT':
            raise ValueError(f'pin: {pin} not set to OUTPUT')
        else:
            if val > 255:
                val = 255
            elif val < 0:
                val = 0
        cmd_str = build_cmd_str("aw", (pin, val))
        write_and_flush(self.sr,cmd_str)

    def analogRead(self, pin):
        """
        Returns the value of a specified
        analog pin.
        inputs:
           pin : analog pin number for measurement
        returns:
           value: integer from 1 to 1023
        """
        pin = int(pin)
        cmd_str = build_cmd_str("ar", (pin,))
        write_and_flush(self.sr,cmd_str)
        try:
            return int(rd(self.sr))
        except:
            return 0

    def pinMode(self, pin, val):
        """
        Sets I/O mode of pin
        inputs:
           pin: pin number to toggle
           val: "INPUT" or "OUTPUT"
        """
        pin = int(pin)
        val = str(val).upper()
        valid= ('INPUT', 'OUTPUT', 'INPUT_PULLUP')
        if val in valid:
            if val == "INPUT":
                pin_ = -pin
            elif val == "INPUT_PULLUP":
                # Arduino ints are 16 bit, so we can use the last bit as a sign value for INPUT_PULLUP
                pin_ = -16384-pin
            else:
                pin_ = pin
            self.pinModeDic[pin] = val
            cmd_str = build_cmd_str("pm", (pin_,))
            write_and_flush(self.sr,cmd_str)
        else:
            raise ValueError(f'val: {str(val).upper()} not in {valid}')

    def pulseIn(self, pin, val):
        """
        Reads a pulse from a pin

        inputs:
           pin: pin number for pulse measurement
        returns:
           duration : pulse length measurement
        """
        pin = int(pin)
        val = str(val).upper()
        valid = ('LOW', 'HIGH')
        if not self.pinModeDic[pin] == 'INPUT':
            raise ValueError(f'pin: {pin} not set to INPUT')
        if not val in valid:
            raise ValueError(f'val: {str(val).upper()} not in {valid}')
        else:
            if val == "LOW":
                pin_ = -pin
            else:
                pin_ = pin
            cmd_str = build_cmd_str("pi", (pin_,))
            write_and_flush(self.sr,cmd_str)
        try:
            return float(rd(self.sr))
        except:
            return -1

    def pulseIn_set(self, pin, val, numTrials=5):
        """
        Sets a digital pin value, then reads the response
        as a pulse width.
        Useful for some ultrasonic rangefinders, etc.

        inputs:
           pin: pin number for pulse measurement
           val: "HIGH" or "LOW". Pulse is measured
                when this state is detected
           numTrials: number of trials (for an average)
        returns:
           duration : an average of pulse length measurements

        This method will automatically toggle
        I/O modes on the pin and precondition the
        measurment with a clean LOW/HIGH pulse.
        Arduino.pulseIn_set(pin,"HIGH") is
        equivalent to the Arduino sketch code:

        pinMode(pin, OUTPUT);
        digitalWrite(pin, LOW);
        delayMicroseconds(2);
        digitalWrite(pin, HIGH);
        delayMicroseconds(5);
        digitalWrite(pin, LOW);
        pinMode(pin, INPUT);
        long duration = pulseIn(pin, HIGH);
        """
        pin = int(pin)
        val = str(val).upper()
        numtrials = int(numtrials)
        if not self.pinModeDic[pin] == 'OUTPUT':
            if val == "LOW":
                pin_ = -pin
            else:
                pin_ = pin
            cmd_str = build_cmd_str("ps", (pin_,))
            durations = []
            for s in range(numTrials):
                write_and_flush(self.sr,cmd_str)
                response=rd(self.sr)
                if response.isdigit():
                    if (int(response) > 1):
                        durations.append(int(response))
        if len(durations) > 0:
            duration = int(sum(durations)) / int(len(durations))
        else:
            duration = None

        try:
            return float(duration)
        except:
            return -1

    def close(self):
        if self.sr.isOpen():
            self.sr.flush()
            self.sr.close()

    def digitalRead(self, pin):
        """
        Returns the value of a specified
        digital pin.
        inputs:
           pin : digital pin number for measurement
        returns:
           value: 0 for "LOW", 1 for "HIGH"
        """
        pin = int(pin)
        if not self.pinModeDic[pin] == 'INPUT':
            raise ValueError('pin: {} not set to INPUT'.format(pin))
        else:
            cmd_str = build_cmd_str("dr", (pin,))
            write_and_flush(self.sr,cmd_str)          
            try:
                return int(rd(self.sr))
            except:
                return 0

    def Melody(self, pin, melody, durations):
        """
        Plays a melody.
        inputs:
            pin: digital pin number for playback
            melody: list of tones
            durations: list of duration (4=quarter note, 8=eighth note, etc.)
        length of melody should be of same
        length as length of duration

        Melodies of the following length, can cause trouble
        when playing it multiple times.
            board.Melody(9,["C4","G3","G3","A3","G3",0,"B3","C4"],
                                                [4,8,8,4,4,4,4,4])
        Playing short melodies (1 or 2 tones) didn't cause
        trouble during testing
        """
        pin = int(pin)
        if not self.pinModeDic[pin] == 'OUTPUT':
                raise ValueError(f'pin: {pin} not initialised to OUTPUT')
        else:
            NOTES = dict(
                B0=31, C1=33, CS1=35, D1=37, DS1=39, E1=41, F1=44, FS1=46, G1=49,
                GS1=52, A1=55, AS1=58, B1=62, C2=65, CS2=69, D2=73, DS2=78, E2=82,
                F2=87, FS2=93, G2=98, GS2=104, A2=110, AS2=117, B2=123, C3=131,
                CS3=139, D3=147, DS3=156, E3=165, F3=175, FS3=185, G3=196, GS3=208,
                A3=220, AS3=233, B3=247, C4=262, CS4=277, D4=294, DS4=311, E4=330,
                F4=349, FS4=370, G4=392, GS4=415, A4=440,
                AS4=466, B4=494, C5=523, CS5=554, D5=587, DS5=622, E5=659, F5=698,
                FS5=740, G5=784, GS5=831, A5=880, AS5=932, B5=988, C6=1047,
                CS6=1109, D6=1175, DS6=1245, E6=1319, F6=1397, FS6=1480, G6=1568,
                GS6=1661, A6=1760, AS6=1865, B6=1976, C7=2093, CS7=2217, D7=2349,
                DS7=2489, E7=2637, F7=2794, FS7=2960, G7=3136, GS7=3322, A7=3520,
                AS7=3729, B7=3951, C8=4186, CS8=4435, D8=4699, DS8=4978)
            if (isinstance(melody, list)) and (isinstance(durations, list)):
                length = len(melody)
                cmd_args = [length, pin]
                if length == len(durations):
                    cmd_args.extend([NOTES.get(melody[note])
                                     for note in range(length)])
                    cmd_args.extend([durations[duration]
                                     for duration in range(len(durations))])
                    cmd_str = build_cmd_str("to", cmd_args)
                    write_and_flush(self.sr,cmd_str)
                    cmd_str = build_cmd_str("nto", [pin])
                    write_and_flush(self.sr,cmd_str)
                else:
                    return -1
            else:
                return -1

    def capacitivePin(self, pin):
        '''
        Input:
            pin (int): pin to use as capacitive sensor

        Use it in a loop!
        DO NOT CONNECT ANY ACTIVE DRIVER TO THE USED PIN !

        the pin is toggled to output mode to discharge the port,
        and if connected to a voltage source,
        will short circuit the pin, potentially damaging
        the Arduino/Shrimp and any hardware attached to the pin.
        '''
        pin = int(pin)
        cmd_str = build_cmd_str("cap", (pin,))
        self.sr.write(cmd_str)
        response = rd(self.sr)
        if response.isdigit():
            return int(response)

    def shiftOut(self, dataPin, clockPin, pinOrder, value):
        """
        Shift a byte out on the datapin using Arduino's shiftOut()

        Input:
            dataPin (int): pin for data
            clockPin (int): pin for clock
            pinOrder (String): either 'MSBFIRST' or 'LSBFIRST'
            value (int): an integer from 0 and 255
        """
        dataPin = int(dataPin)
        clockPin = int(clockPin)
        pinOrder = str(pinOrder).upper()
        value = int(value)
        valid = ('MSBFIRST', 'LSBFIRST')
        if self.pinModeDic[dataPin] == 'OUTPUT' and self.pinModeDic[clockPin] == 'OUTPUT' and pinOrder.upper() in valid:
            if value < 0:
                value = 0
            elif value > 255:
                value = 255
            cmd_str = build_cmd_str("so",
                                   (dataPin, clockPin, pinOrder, value))
            write_and_flush(self.sr, cmd_str, raise_error=True)
        else:
            if not self.pinModeDic[dataPin] == 'OUTPUT':
                raise ValueError('pin: {} not initialised to OUTPUT'.format(dataPin))
            if not self.pinModeDic[clockPin] == 'OUTPUT':
                raise ValueError('pin: {} not initialised to OUTPUT'.format(clockPin))
            if not pinOrder.upper() in valid:
                raise ValueError('pinOrder: {} not in {}'.format(str(pinOrder).upper(), valid))

    def shiftIn(self, dataPin, clockPin, pinOrder):
        """
        Shift a byte in from the datapin using Arduino's shiftIn().

        Input:
            dataPin (int): pin for data
            clockPin (int): pin for clock
            pinOrder (String): either 'MSBFIRST' or 'LSBFIRST'
        Output:
            (int) an integer from 0 to 255
        """
        dataPin = int(dataPin)
        clockPin = int(clockPin)
        pinOrder = str(pinOrder).upper()
        valid = ('MSBFIRST', 'LSBFIRST')
        if self.pinModeDic[dataPin] == 'OUTPUT' and self.pinModeDic[clockPin] == 'OUTPUT' and pinOrder.upper() in valid:
            cmd_str = build_cmd_str("si",
                                   (dataPin, clockPin, pinOrder))
            write_and_flush(self.sr,cmd_str)
            response = rd(self.sr)
            if response.isdigit():
                return int(response)
        else:
            if not self.pinModeDic[dataPin] == 'OUTPUT':
                raise ValueError(f'pin: {dataPin} not initialised to OUTPUT')
            if not self.pinModeDic[clockPin] == 'OUTPUT':
                raise ValueError(f'pin: {clockPin} not initialised to OUTPUT')
            if not pinOrder in valid.upper():
                raise ValueError(f'pinOrder: {str(pinOrder).upper()} not in {valid}')


class Shrimp(Arduino):

    def __init__(self):
        Arduino.__init__(self)


class Wires(object):

    """
    Class for Arduino wire (i2c) support
    """

    def __init__(self, board):
        self.board = board
        self.sr = board.sr


class Servos(object):

    """
    Class for Arduino servo support
    0.03 second delay noted
    """

    def __init__(self, board):
        self.board = board
        self.sr = board.sr
        self.servo_pos = {}

    def attach(self, pin, min=544, max=2400):
        cmd_str = build_cmd_str("sva", (pin, min, max))

        while True:
            write_and_flush(self.sr,cmd_str, raise_error=True)
            response = rd(self.sr)
            if response:
                break #What does this do?
            else:
                log.debug(f"trying to attach servo to pin {pin}")
        position = int(response)
        self.servo_pos[pin] = position
        return 1

    def detach(self, pin):
        position = self.servo_pos[pin]
        cmd_str = build_cmd_str("svd", (position,))
        write_and_flush(self.sr,cmd_str)
        del self.servo_pos[pin]

    def write(self, pin, angle):
        position = self.servo_pos[pin]
        cmd_str = build_cmd_str("svw", (position, angle))

        write_and_flush(self.sr,cmd_str,raise_errors=True)

    def writeMicroseconds(self, pin, uS):
        position = self.servo_pos[pin]
        cmd_str = build_cmd_str("svwm", (position, uS))

       write_and_flush(self.sr,cmd_str,raise_errors=True)

    def read(self, pin):
        if pin not in self.servo_pos.keys():
            self.attach(pin)
        position = self.servo_pos[pin]
        cmd_str = build_cmd_str("svr", (position,))
        write_and_flush(self.sr,cmd_str)
        try:
            angle = int(rd(self.sr))
            return angle
        except:
            return None



class SoftwareSerial(object):

    """
    Class for Arduino software serial functionality
    """

    def __init__(self, board):
        self.board = board
        self.sr = board.sr
        self.connected = False

    def begin(self, p1, p2, baud):
        """
        Create software serial instance on
        specified tx,rx pins, at specified baud
        """
        cmd_str = build_cmd_str("ss", (p1, p2, baud))
        write_and_flush(self.sr,cmd_str)   
        response = rd(self.sr)
        if response == "ss OK":
            self.connected = True
            return True
        else:
            self.connected = False
            return False

    def write(self, data):
        """
        sends data to existing software serial instance
        using Arduino's 'write' function
        """
        if self.connected:
            cmd_str = build_cmd_str("sw", (data,))
            write_and_flush(self.sr,cmd_str)    
            response = rd(self.sr)
            if response == "ss OK":
                return True
        else:
            return False

    def read(self):
        """
        returns first character read from
        existing software serial instance
        """
        if self.connected:
            cmd_str = build_cmd_str("sr")
            write_and_flush(self.sr,cmd_str, raise_error=True)
            response = rd(self.sr)
            if response:
                return response
        else:
            return False


class EEPROM(object):
    """
    Class for reading and writing to EEPROM.
    """

    def __init__(self, board):
        self.board = board
        self.sr = board.sr

    def size(self):
        """
        Returns size of EEPROM memory.
        """
        cmd_str = build_cmd_str("sz")

        try:
            write_and_flush(self.sr,cmd_str, raise_error=True)       
            response = rd(self.sr)
            return int(response)
        except:
            return 0

    def write(self, address, value=0):
        """ Write a byte to the EEPROM.

        :address: the location to write to, starting from 0 (int)
        :value: the value to write, from 0 to 255 (byte)
        @TODO Implement checking here
        """
        address = int(address)

        if value > 255:
            value = 255
        elif value < 0:
            value = 0
        cmd_str = build_cmd_str("eewr", (address, value))
        write_and_flush(self.sr,cmd_str)

    def read(self, address):
        """ Reads a byte from the EEPROM.

        :address: the location to read from, starting from 0 (int)
        """
        address = int(address)
        cmd_str = build_cmd_str("eer", (address,))
        try:
            write_and_flush(self.sr,cmd_str)                
            response = rd(self.sr)
            if response:
                return int(response)
        except:
            return 0
