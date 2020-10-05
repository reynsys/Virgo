import os
import sys
import argparse
import time
import numpy as np

def observe(obs_parameters, obs_file='observation.dat', start_in=0):
	from run_observation import run_observation

	dev_args = '"'+obs_parameters['dev_args']+'"'
	rf_gain = obs_parameters['rf_gain']
	if_gain = obs_parameters['if_gain']
	bb_gain = obs_parameters['bb_gain']
	frequency = obs_parameters['frequency']
	bandwidth = obs_parameters['bandwidth']
	channels = obs_parameters['channels']
	t_sample = obs_parameters['t_sample']
	duration = obs_parameters['duration']

	# Schedule observation
	#if start_in != 0:
	#	print('[*] The observation will begin in '+str(start_in)+' sec automatically. Please wait...\n')

	time.sleep(start_in)

	# Delete pre-existing observation file
	try:
		os.remove(obs_file)
	except OSError:
		pass

	# Note current datetime
	epoch = time.time()

	# Convert timestamp to MJD
	mjd = epoch/86400.0 + 40587

	# Run observation
	#print('\n[+] Starting observation at ' + time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(epoch)) + '...\n')

	observation = run_observation(dev_args=dev_args, frequency=frequency, bandwidth=bandwidth, rf_gain=rf_gain,
                              if_gain=if_gain, bb_gain=bb_gain, channels=channels,
							  duration=duration, t_sample=t_sample, obs_file=obs_file)
	observation.start()
	observation.wait()

	#print('\n[+] Data acquisition complete. Observation saved as: '+obs_file)

	# Write observation parameters to header file
	with open('.'.join(obs_file.split('.')[:-1])+'.header', 'w') as f:
		f.write('''mjd='''+str(mjd)+'''
dev_args='''+str(dev_args)+'''
rf_gain='''+str(rf_gain)+'''
if_gain='''+str(if_gain)+'''
bb_gain='''+str(bb_gain)+'''
frequency='''+str(frequency)+'''
bandwidth='''+str(bandwidth)+'''
channels='''+str(channels)+'''
t_sample='''+str(t_sample)+'''
duration='''+str(duration))

def plot(obs_parameters='', n=0, m=0, f_rest=0, dB=False, obs_file='observation.dat',
         cal_file='', waterfall_fits='', spectra_csv='', power_csv='', plot_file='plot.png'):
	import matplotlib
	matplotlib.use('Agg') # Try commenting this line if you run into display/rendering errors
	import matplotlib.pyplot as plt
	from matplotlib.gridspec import GridSpec

	plt.rcParams['legend.fontsize'] = 14
	plt.rcParams['axes.labelsize'] = 14
	plt.rcParams['axes.titlesize'] = 18
	plt.rcParams['xtick.labelsize'] = 12
	plt.rcParams['ytick.labelsize'] = 12

	def decibel(x):
		if dB: return 10.0*np.log10(x)
		return x

	def SNR(spectrum, mask=np.array([])):
		'''Signal-to-Noise Ratio estimator, with optional masking.
		If mask not given, then all channels will be used to estimate noise
		(will drastically underestimate S:N - not robust to outliers!)'''

		if mask.size == 0:
			mask = np.zeros_like(spectrum)

		noise = np.std((spectrum[2:]-spectrum[:-2])[mask[1:-1] == 0])/np.sqrt(2)
		background = np.nanmean(spectrum[mask == 0])

		return (spectrum-background)/noise

	def best_fit(power):
		'''Compute best Gaussian fit'''
		avg = np.mean(power)
		var = np.var(power)

		gaussian_fit_x = np.linspace(np.min(power),np.max(power),100)
		gaussian_fit_y = 1.0/np.sqrt(2*np.pi*var)*np.exp(-0.5*(gaussian_fit_x-avg)**2/var)

		return [gaussian_fit_x, gaussian_fit_y]

	# Load observation parameters from dictionary argument/header file
	if obs_parameters != '':
		frequency = obs_parameters['frequency']
		bandwidth = obs_parameters['bandwidth']
		channels = obs_parameters['channels']
		t_sample = obs_parameters['t_sample']
	else:
		header_file = '.'.join(obs_file.split('.')[:-1])+'.header'

		print('[!] No observation parameters passed. Attempting to load from header file ('+header_file+')...')

		with open(header_file, 'r') as f:
			headers = [parameter.rstrip('\n') for parameter in f.readlines()]

		for i in range(len(headers)):
			if 'mjd' in headers[i]:
				mjd = float(headers[i].strip().split('=')[1])
			elif 'frequency' in headers[i]:
				frequency = float(headers[i].strip().split('=')[1])
			elif 'bandwidth' in headers[i]:
				bandwidth = float(headers[i].strip().split('=')[1])
			elif 'channels' in headers[i]:
				channels = int(headers[i].strip().split('=')[1])
			elif 't_sample' in headers[i]:
				t_sample = float(headers[i].strip().split('=')[1])

	# Define Relative Velocity axis limits
	left_velocity_edge = -299792.458*(bandwidth-2*frequency+2*f_rest)/(bandwidth-2*frequency)
	right_velocity_edge = 299792.458*(-bandwidth-2*frequency+2*f_rest)/(bandwidth+2*frequency)

	# Transform sampling time to number of bins
	bins = int(t_sample*bandwidth/channels)

	# Load observation & calibration data
	offset = 1
	waterfall = offset*np.fromfile(obs_file, dtype='float32').reshape(-1, channels)/bins

	if cal_file != '': waterfall_cal = offset*np.fromfile(cal_file, dtype='float32').reshape(-1, channels)/bins

	# Compute average specta
	avg_spectrum = decibel(np.mean(waterfall, axis=0))
	if cal_file != '': avg_spectrum_cal = decibel(np.nanmean(waterfall_cal, axis=0))

	# Define array for Time Series plot
	power = decibel(np.mean(waterfall, axis=1))

	# Number of sub-integrations
	subs = waterfall.shape[0]

	# Compute Time axis
	t = t_sample*np.arange(subs)

	# Compute Frequency axis; convert Hz to MHz
	frequency = np.linspace(frequency-0.5*bandwidth, frequency+0.5*bandwidth,
	                        channels, endpoint=False)*1e-6

	# Apply Mask
	mask = np.zeros_like(avg_spectrum)
	mask[np.logical_and(frequency > f_rest*1e-6-0.2, frequency < f_rest*1e-6+0.8)] = 1 # Margins OK for galactic HI

	# Define text offset for axvline text label
	text_offset = 0

	# Calibrate Spectrum
	if cal_file != '':
		if dB:
			spectrum = 10**((avg_spectrum-avg_spectrum_cal)/10)
		else:
			spectrum = avg_spectrum/avg_spectrum_cal

		# Mitigate RFI (Frequency Domain)
		if n != 0:
			spectrum_clean = SNR(spectrum.copy(), mask)
			for i in range(0, int(channels)):
				spectrum_clean[i] = np.median(spectrum_clean[i:i+n])

		spectrum = SNR(spectrum, mask)

		# Apply position offset for Spectral Line label
		text_offset = 60

	# Mitigate RFI (Time Domain)
	if m != 0:
		power_clean = power.copy()
		for i in range(0, int(subs)):
			power_clean[i] = np.median(power_clean[i:i+m])

	# Write Waterfall to file (FITS)
	if waterfall_fits != '':
		from astropy.io import fits

		# Load data
		hdu = fits.PrimaryHDU(waterfall)

		# Prepare FITS headers
		hdu.header['NAXIS'] = 2
		hdu.header['NAXIS1'] = channels
		hdu.header['NAXIS2'] = subs
		hdu.header['CRPIX1'] = channels/2
		hdu.header['CRPIX2'] = subs/2
		hdu.header['CRVAL1'] = frequency[channels/2]
		hdu.header['CRVAL2'] = t[subs/2]
		hdu.header['CDELT1'] = bandwidth*1e-6/channels
		hdu.header['CDELT2'] = t_sample
		hdu.header['CTYPE1'] = 'Frequency (MHz)'
		hdu.header['CTYPE2'] = 'Relative Time (s)'
		try:
			hdu.header['MJD-OBS'] = mjd
		except NameError:
			print('[!] Observation MJD could not be found and will not be part of the FITS header. Ignoring...')
			pass

		# Delete pre-existing FITS file
		try:
			os.remove(waterfall_fits)
		except OSError:
			pass

		# Write to file
		hdu.writeto(waterfall_fits)

	# Write Spectra to file (csv)
	if spectra_csv != '':
		if cal_file != '':
			np.savetxt(spectra_csv, np.concatenate((frequency.reshape(channels, 1),
                       avg_spectrum.reshape(channels, 1), avg_spectrum_cal.reshape(channels, 1),
                       spectrum.reshape(channels, 1)), axis=1), delimiter=',', fmt='%1.3f')
		else:
			np.savetxt(spectra_csv, np.concatenate((frequency.reshape(channels, 1),
                       avg_spectrum.reshape(channels, 1)), axis=1), delimiter=',', fmt='%1.3f')

	# Write Time Series to file (csv)
	if power_csv != '':
		np.savetxt(power_csv, np.concatenate((t.reshape(subs, 1), power.reshape(subs, 1)),
                   axis=1), delimiter=',', fmt='%1.3f')

	# Initialize plot
	if cal_file != '':
		fig = plt.figure(figsize=(27, 15))
		gs = GridSpec(2, 3)
	else:
		fig = plt.figure(figsize=(21, 15))
		gs = GridSpec(2, 2)

	# Plot Average Spectrum
	ax1 = fig.add_subplot(gs[0, 0])
	ax1.plot(frequency, avg_spectrum)
	ax1.set_xlim(np.min(frequency), np.max(frequency))
	ax1.ticklabel_format(useOffset=False)
	ax1.set_xlabel('Frequency (MHz)')
	if dB:
		ax1.set_ylabel('Relative Power (dB)')
	else:
		ax1.set_ylabel('Relative Power')
	if f_rest != 0 and sys.version_info[0] < 3:
		ax1.set_title('Average Spectrum\n')
	else:
		ax1.set_title('Average Spectrum')
	ax1.grid()

	if f_rest != 0:
		# Add secondary axis for Relative Velocity
		ax1_secondary = ax1.twiny()
		ax1_secondary.set_xlabel('Relative Velocity (km/s)', labelpad=5)
		ax1_secondary.axvline(x=0, color='brown', linestyle='--', linewidth=2, zorder=0)
		ax1_secondary.annotate('Spectral Line\nRest Frequency', xy=(460-text_offset, 5),
                               xycoords='axes points', size=14, ha='left', va='bottom', color='brown')
		ax1_secondary.set_xlim(left_velocity_edge, right_velocity_edge)
		ax1_secondary.tick_params(axis='x', direction='in', pad=-22)

	#Plot Calibrated Spectrum
	if cal_file != '':
		ax2 = fig.add_subplot(gs[0, 1])
		ax2.plot(frequency, spectrum, label='Raw Spectrum')
		if n != 0:
			ax2.plot(frequency, spectrum_clean, color='orangered', label='Median (n = '+str(n)+')')
			ax2.set_ylim()
		ax2.set_xlim(np.min(frequency), np.max(frequency))
		ax2.ticklabel_format(useOffset=False)
		ax2.set_xlabel('Frequency (MHz)')
		ax2.set_ylabel('Signal-to-Noise Ratio (S/N)')
		if f_rest != 0 and sys.version_info[0] < 3:
			ax2.set_title('Calibrated Spectrum\n')
		else:
			ax2.set_title('Calibrated Spectrum')
		if n != 0:
			if f_rest != 0:
				ax2.legend(bbox_to_anchor=(0.002, 0.96), loc='upper left')
			else:
				ax2.legend(loc='upper left')

		if f_rest != 0:
			# Add secondary axis for Relative Velocity
			ax2_secondary = ax2.twiny()
			ax2_secondary.set_xlabel('Relative Velocity (km/s)', labelpad=5)
			ax2_secondary.axvline(x=0, color='brown', linestyle='--', linewidth=2, zorder=0)
			ax2_secondary.annotate('Spectral Line\nRest Frequency', xy=(400, 5),
                                   xycoords='axes points', size=14, ha='left', va='bottom', color='brown')
			ax2_secondary.set_xlim(left_velocity_edge, right_velocity_edge)
			ax2_secondary.tick_params(axis='x', direction='in', pad=-22)
		ax2.grid()

	# Plot Dynamic Spectrum
	if cal_file != '':
		ax3 = fig.add_subplot(gs[0, 2])
	else:
		ax3 = fig.add_subplot(gs[0, 1])
	ax3.imshow(decibel(waterfall), origin='lower', interpolation='None', aspect='auto',
               extent=[np.min(frequency), np.max(frequency), np.min(t), np.max(t)])
	ax3.ticklabel_format(useOffset=False)
	ax3.set_xlabel('Frequency (MHz)')
	ax3.set_ylabel('Relative Time (s)')
	ax3.set_title('Dynamic Spectrum (Waterfall)')

	# Adjust Subplot Width Ratio
	if cal_file != '':
		gs = GridSpec(2, 3, width_ratios=[16.5, 1, 1])
	else:
		gs = GridSpec(2, 2, width_ratios=[7.6, 1])

	# Plot Time Series (Power vs Time)
	ax4 = fig.add_subplot(gs[1, 0])
	ax4.plot(t, power, label='Raw Time Series')
	if m != 0:
		ax4.plot(t, power_clean, color='orangered', label='Median (n = '+str(m)+')')
		ax4.set_ylim()
	ax4.set_xlim(0, np.max(t))
	ax4.set_xlabel('Relative Time (s)')
	if dB:
		ax4.set_ylabel('Relative Power (dB)')
	else:
		ax4.set_ylabel('Relative Power')
	ax4.set_title('Average Power vs Time')
	if m != 0:
		ax4.legend(bbox_to_anchor=(1, 1), loc='upper right')
	ax4.grid()

	# Plot Total Power Distribution
	if cal_file != '':
		gs = GridSpec(2, 3, width_ratios=[7.83, 1.5, -0.325])
	else:
		gs = GridSpec(2, 2, width_ratios=[8.8, 1.5])

	ax5 = fig.add_subplot(gs[1, 1])

        ax5.hist(power, np.max([int(np.size(power)/50),10]), density=1, alpha=0.5, color='royalblue', orientation='horizontal', zorder=10)
        ax5.plot(best_fit(power)[1], best_fit(power)[0], '--', color='blue', label='Best fit (Raw)', zorder=20)
        if m != 0:
                ax5.hist(power_clean, np.max([int(np.size(power)/50),10]), density=1, alpha=0.5, color='orangered', orientation='horizontal', zorder=10)
                ax5.plot(best_fit(power_clean)[1], best_fit(power)[0], '--', color='red', label='Best fit (Median)', zorder=20)
        ax5.set_xlim()
        ax5.set_ylim()
        ax5.get_shared_x_axes().join(ax5, ax4)
        ax5.set_yticklabels([])
        ax5.set_xlabel('Probability Density')
        ax5.set_title('Total Power Distribution')
        ax5.legend(bbox_to_anchor=(1, 1), loc='upper right')
        ax5.grid()

	# Save plots to file
	plt.tight_layout()
	plt.savefig(plot_file)

if __name__ == '__main__':
	# Load argument values
	parser = argparse.ArgumentParser()

	parser.add_argument('-da', '--dev_args', dest='dev_args',
                        help='SDR Device Arguments (osmocom Source)', type=str, default='""')
	parser.add_argument('-rf', '--rf_gain', dest='rf_gain',
                        help='SDR RF Gain (dB)', type=float, default=10)
	parser.add_argument('-if', '--if_gain', dest='if_gain',
                        help='SDR IF Gain (dB)', type=float, default=20)
	parser.add_argument('-bb', '--bb_gain', dest='bb_gain',
                        help='SDR BB Gain (dB)', type=float, default=20)
	parser.add_argument('-f', '--frequency', dest='frequency',
                        help='Center Frequency (Hz)', type=float, required=True)
	parser.add_argument('-b', '--bandwidth', dest='bandwidth',
                        help='Bandwidth (Hz)', type=float, required=True)
	parser.add_argument('-c', '--channels', dest='channels',
                        help='Number of Channels (FFT Size)', type=int, required=True)
	parser.add_argument('-t', '--t_sample', dest='t_sample',
                        help='FFT Sample Time (s)', type=float, required=True)
	parser.add_argument('-d', '--duration', dest='duration',
                        help='Observing Duration (s)', type=float, default=60)
	parser.add_argument('-s', '--start_in', dest='start_in',
                        help='Schedule Observation (s)', type=float, default=0)
	parser.add_argument('-o', '--obs_file', dest='obs_file',
                        help='Observation Filename', type=str, default='observation.dat')
	parser.add_argument('-C', '--cal_file', dest='cal_file',
                        help='Calibration Filename', type=str, default='')
	parser.add_argument('-db', '--db', dest='dB',
                        help='Use dB-scaled Power values', default=False, action='store_true')
	parser.add_argument('-n', '--median_frequency', dest='n',
                        help='Median Factor (Frequency Domain)', type=int, default=0)
	parser.add_argument('-m', '--median_time', dest='m',
                        help='Median Factor (Time Domain)', type=int, default=0)
	parser.add_argument('-r', '--rest_frequency', dest='f_rest',
                        help='Spectral Line Rest Frequency (Hz)', type=float, default=0)
	parser.add_argument('-W', '--waterfall_fits', dest='waterfall_fits',
                        help='Filename for FITS Waterfall File', type=str, default='')
	parser.add_argument('-S', '--spectra_csv', dest='spectra_csv',
                        help='Filename for Spectra csv File', type=str, default='')
	parser.add_argument('-P', '--power_csv', dest='power_csv',
                        help='Filename for Spectra csv File', type=str, default='')
	parser.add_argument('-p', '--plot_file', dest='plot_file',
                        help='Plot Filename', type=str, default='plot.png')

	args = parser.parse_args()

	# Define data-acquisition parameters
	observation = {
	'dev_args': args.dev_args,
    'rf_gain': args.rf_gain,
    'if_gain': args.if_gain,
    'bb_gain': args.bb_gain,
    'frequency': args.frequency,
    'bandwidth': args.bandwidth,
    'channels': args.channels,
    't_sample': args.t_sample,
    'duration': args.duration
	}

	# Acquire data from SDR
	observe(obs_parameters=observation, obs_file=args.obs_file, start_in=args.start_in)

	# Plot data
	plot(obs_parameters=observation, n=args.n, m=args.m, f_rest=args.f_rest,
	     dB=args.dB, obs_file=args.obs_file, cal_file=args.cal_file, waterfall_fits=args.waterfall_fits,
		 spectra_csv=args.spectra_csv, power_csv=args.power_csv, plot_file=args.plot_file)
