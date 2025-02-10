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


def detect_sdr():
    sdr_list = SoapySDR.Device.enumerate()
    if not sdr_list:
        raise RuntimeError("No SDR devices found!")
    return sdr_list[0]['driver']

def parse_args():
    """Parse command line arguments with proper validation"""
    parser = argparse.ArgumentParser(
        description="DVB-S2 SDR Transmitter",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # SDR Parameters
    parser.add_argument("--freq", type=float, default=2.4e9,
                        help="Transmission frequency in Hz (e.g., 2.4e9 for 2.4 GHz)")
    parser.add_argument("--rate", type=float, default=2e6,
                        help="Sample rate in Hz (e.g., 2e6 for 2 MHz)")
    parser.add_argument("--gain", type=float, default=30,
                        help="SDR gain in dB (0-70)")

    # DVB-S2 Parameters
    parser.add_argument("--modcod", choices=['QPSK1/2', 'QPSK3/4', '8PSK2/3', '8PSK5/6'],
                        default='QPSK1/2', help="Modulation and coding scheme")
    parser.add_argument("--pilots", action="store_true", default=True,
                        help="Enable pilot symbols")
    parser.add_argument("--rolloff", type=float, choices=[0.2, 0.25, 0.35],
                        default=0.35, help="Roll-off factor")


    # Stream Parameters
    parser.add_argument("--port", type=int, default=5004,
                        help="UDP port for MPEG-TS stream")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug output and logging")

    args = parser.parse_args()

    # Validate frequency range
    if not 70e6 <= args.freq <= 6e9:
        parser.error("Frequency must be between 70 MHz and 6 GHz")

    # Validate sample rate
    if not 1e6 <= args.rate <= 56e6:
        parser.error("Sample rate must be between 1 MHz and 56 MHz")

    # Validate gain
    if not 0 <= args.gain <= 70:
        parser.error("Gain must be between 0 and 70 dB")

    return args


class DVBS2Transmitter(gr.top_block):
    def __init__(self, args):
        gr.top_block.__init__(self, "DVB-S2 Transmitter")

        # Store configuration
        self.args = args

        # Map modcod string to GNU Radio constants
        self.modcod_map = {
            'QPSK1/2': (dtv.MOD_QPSK, dtv.C1_2),
            'QPSK3/4': (dtv.MOD_QPSK, dtv.C3_4),
            '8PSK2/3': (dtv.MOD_8PSK, dtv.C2_3),
            '8PSK5/6': (dtv.MOD_8PSK, dtv.C5_6)
        }

        # Get modulation and coding from map
        self.constellation, self.code_rate = self.modcod_map[args.modcod]

        # Map rolloff to GNU Radio constants
        self.rolloff_map = {
            0.20: dtv.RO_0_20,
            0.25: dtv.RO_0_25,
            0.35: dtv.RO_0_35
        }

        self.setup_blocks()
        self.connect_blocks()

    def setup_blocks(self):
        """Initialize all GNU Radio blocks with CLI parameters"""
        try:
            # MPEG-TS Source
            self.ts_source = blocks.udp_source(
                itemsize=gr.sizeof_char,
                ipaddr="127.0.0.1",
                port=self.args.port,
                payload_size=1472
            )

            # DVB-S2 Modulation Chain
            self.bbheader = dtv.dvb_bbheader_bb(
                standard=dtv.STANDARD_DVBS2,
                framesize=dtv.FECFRAME_NORMAL,
                rate=self.code_rate,
                rolloff=self.rolloff_map[self.args.rolloff]
            )

            self.bbscrambler = dtv.dvb_bbscrambler_bb(
                standard=dtv.STANDARD_DVBS2,
                framesize=dtv.FECFRAME_NORMAL,
                rate=self.code_rate
            )

            self.bch = dtv.dvb_bch_bb(
                standard=dtv.STANDARD_DVBS2,
                framesize=dtv.FECFRAME_NORMAL,
                rate=self.code_rate
            )

            self.ldpc = dtv.dvb_ldpc_bb(
                standard=dtv.STANDARD_DVBS2,
                framesize=dtv.FECFRAME_NORMAL,
                rate=self.code_rate,
                constellation=self.constellation
            )

            self.modulator = dtv.dvbs2_modulator_bc(
                framesize=dtv.FECFRAME_NORMAL,
                rate=self.code_rate,
                constellation=self.constellation,
                interpolation=2,
                goldcode=0
            )

            self.physical = dtv.dvbs2_physical_cc(
                framesize=dtv.FECFRAME_NORMAL,
                rate=self.code_rate,
                constellation=self.constellation,
                pilots=dtv.PILOTS_ON if self.args.pilots else dtv.PILOTS_OFF,
                goldcode=0
            )

            # Setup SDR with detected device
            sdr_args = detect_sdr()
            self.sdr_sink = osmosdr.sink(args=sdr_args)

            # Configure SDR parameters from CLI args
            self.sdr_sink.set_sample_rate(self.args.rate)
            self.sdr_sink.set_center_freq(self.args.freq)
            self.sdr_sink.set_gain(self.args.gain)
            self.sdr_sink.set_bandwidth(self.args.rate)

            if self.args.debug:
                print(f"\nSDR Configuration:")
                print(f"Frequency: {self.args.freq / 1e6:.2f} MHz")
                print(f"Sample Rate: {self.args.rate / 1e6:.2f} MHz")
                print(f"Gain: {self.args.gain} dB")
                print(f"Modulation: {self.args.modcod}")
                print(f"Roll-off: {self.args.rolloff}")
                print(f"Pilots: {'Enabled' if self.args.pilots else 'Disabled'}")

        except Exception as e:
            print(f"Error setting up blocks: {e}")
            sys.exit(1)

    def connect_blocks(self):
        """Connect all blocks in the flowgraph"""
        try:
            self.connect(
                self.ts_source,
                self.bbheader,
                self.bbscrambler,
                self.bch,
                self.ldpc,
                self.modulator,
                self.physical,
                self.sdr_sink
            )
        except Exception as e:
            print(f"Error connecting blocks: {e}")
            sys.exit(1)


def start_gstreamer(port):
    """Start GStreamer pipeline for MPEG-TS streaming"""
    gst_cmd = f"gst-launch-1.0 -v udpsrc port={port -1} ! tsparse ! dvbs2enc ! udpsink host=127.0.0.1 port={port}"
    return subprocess.Popen(gst_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def signal_handler(sig, frame):
    print("Terminating DVB-S2 Transmission...")
    sys.exit(0)


#################################################################################################
##Main Function###

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)

    # Parse command line arguments
    args = parse_args()

    print(f"Starting DVB-S2 Transmission...")

    # Start GStreamer
    gst_process = start_gstreamer(args.port)
    if not gst_process:
        sys.exit(1)

    time.sleep(2)

    try:
        tb = DVBS2Transmitter(args)
        tb.start()

        print("Transmission started. Press Enter to quit...")
        input()

    except Exception as e:
        print(f"Error during transmission: {e}")
    finally:
        if 'gst_process' in globals():
            gst_process.terminate()
        if 'tb' in globals():
            tb.stop()
            tb.wait()