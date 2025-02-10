# Basic usage with default parameters
python3 tx_dvb-s2.py

# Custom frequency and sample rate
python3 tx_dvb-s2.py --freq 2425000000 --rate 5e6

# Full configuration
python3 tx_dvb-s2.py --freq 2.4e9 --rate 2e6 --gain 40 --modcod QPSK3/4 --rolloff 0.25 --pilots --debug

# Help message
python3 tx_dvb-s2.py --help
Would you like me to:

Add more modulation schemes?
Add configuration file support?
Add real-time parameter adjustment capabilities?
Running the receive script.
python3 dvbs2_receive.py --freq 2400000000 --rate 2e6 --gain 40 --modcod QPSK1/2 --port 5004
