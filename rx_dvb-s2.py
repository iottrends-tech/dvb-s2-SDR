import os
import sys
import time
import signal
import argparse
import numpy as np
import subprocess
from gnuradio import gr, blocks, dtv
import osmosdr
import SoapySDR


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(description="DVB-S2 SDR Receiver")

    parser.add_argument("--freq", type=float, default=2.4e9,
                        help="Receive frequency in Hz (e.g., 2.4e9 for 2.4 GHz)")
    parser.add_argument("--rate", type=float, default=2e6,
                        help="Sample rate in Hz (e.g., 2e6 for 2 MHz)")
    parser.add_argument("--gain", type=float, default=40,
                        help="SDR gain in dB (0-70)")
    parser.add_argument("--modcod", choices=['QPSK1/2', 'QPSK3/4', '8PSK2/3', '8PSK5/6'],
                        default='QPSK1/2', help="Modulation and coding scheme")
    parser.add_argument("--rolloff", type=float, choices=[0.2, 0.25, 0.35],
                        default=0.35, help="Roll-off factor")
    parser.add_argument("--port", type=int, default=5004,
                        help="UDP port for MPEG-TS output")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug output and logging")

    return parser.parse_args()


class DVBS2Receiver(gr.top_block):
    def __init__(self, args):
        gr.top_block.__init__(self, "DVB-S2 Receiver")

        self.args = args

        # Map modulation and coding scheme to GNU Radio constants
        self.modcod_map = {
            'QPSK1/2': (dtv.MOD_QPSK, dtv.C1_2),
            'QPSK3/4': (dtv.MOD_QPSK, dtv.C3_4),
            '8PSK2/3': (dtv.MOD_8PSK, dtv.C2_3),
            '8PSK5/6': (dtv.MOD_8PSK, dtv.C5_6)
        }

        self.constellation, self.code_rate = self.modcod_map[args.modcod]

        # Setup GNU Radio blocks
        self.setup_blocks()
        self.connect_blocks()

    def setup_blocks(self):
        """Initialize SDR and DVB-S2 demodulation blocks"""
        try:
            # SDR Source Block
            sdr_args = detect_sdr()
            self.sdr_source = osmosdr.source(args=sdr_args)
            self.sdr_source.set_sample_rate(self.args.rate)
            self.sdr_source.set_center_freq(self.args.freq)
            self.sdr_source.set_gain(self.args.gain)
            self.sdr_source.set_bandwidth(self.args.rate)

            # DVB-S2 Demodulator
            self.demodulator = dtv.dvbs2_demodulator(
                framesize=dtv.FECFRAME_NORMAL,
                rate=self.code_rate,
                constellation=self.constellation,
                pilots=dtv.PILOTS_ON,
                rolloff=self.args.rolloff
            )

            # Transport Stream Output via UDP
            self.ts_sink = blocks.udp_sink(
                itemsize=gr.sizeof_char,
                ipaddr="127.0.0.1",
                port=self.args.port,
                payload_size=1472
            )

            if self.args.debug:
                print(f"\nSDR Receiver Configuration:")
                print(f"Frequency: {self.args.freq / 1e6:.2f} MHz")
                print(f"Sample Rate: {self.args.rate / 1e6:.2f} MHz")
                print(f"Gain: {self.args.gain} dB")
                print(f"Modulation: {self.args.modcod}")
                print(f"Roll-off: {self.args.rolloff}")

        except Exception as e:
            print(f"Error setting up receiver: {e}")
            sys.exit(1)

    def connect_blocks(self):
        """Connect SDR source to demodulator and UDP output"""
        try:
            self.connect(self.sdr_source, self.demodulator, self.ts_sink)
        except Exception as e:
            print(f"Error connecting blocks: {e}")
            sys.exit(1)


def detect_sdr():
    """Detect and configure SDR automatically"""
    try:
        devices = SoapySDR.Device.enumerate()
        if not devices:
            print("No SDR devices found!")
            sys.exit(1)

        device_info = devices[0]
        driver = device_info.get('driver', '').lower()

        driver_map = {
            'lime': 'driver=lime,soapy=0',
            'pluto': 'driver=plutosdr,soapy=0',
            'hackrf': 'driver=hackrf,soapy=0',
            'rtlsdr': 'driver=rtl,soapy=0',
            'uhd': 'driver=uhd,soapy=0',
            'bladerf': 'driver=bladerf,soapy=0'
        }

        osmosdr_args = driver_map.get(driver, f"driver={driver},soapy=0")
        print(f"Detected SDR: {device_info['label']} (Driver: {driver})")

        return osmosdr_args
    except Exception as e:
        print(f"Error detecting SDR: {e}")
        sys.exit(1)


def start_vlc(port):
    """Start VLC to play the received MPEG-TS stream"""
    vlc_command = f"cvlc udp://@: {port} --network-caching=100"

    try:
        process = subprocess.Popen(vlc_command, shell=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return process
    except Exception as e:
        print(f"Error starting VLC: {e}")
        return None


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda sig, frame: sys.exit(0))

    # Parse CLI arguments
    args = parse_args()

    print(f"Starting DVB-S2 Receiver...")

    try:
        # Start VLC for playback
        vlc_process = start_vlc(args.port)

        # Create and start the receiver
        tb = DVBS2Receiver(args)
        tb.start()

        print("Receiving and decoding DVB-S2 signal. Press Ctrl+C to stop.")
        signal.pause()  # Keep script running until Ctrl+C

    except Exception as e:
        print(f"Error during reception: {e}")
    finally:
        if 'vlc_process' in globals():
            vlc_process.terminate()
        if 'tb' in globals():
            tb.stop()
            tb.wait()
