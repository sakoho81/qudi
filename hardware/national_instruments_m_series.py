# -*- coding: utf-8 -*-

"""
This file contains the Qudi Hardware module for the NI 6229 card.

Qudi is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Qudi is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Qudi. If not, see <http://www.gnu.org/licenses/>.

Copyright (c) the Qudi Developers. See the COPYRIGHT.txt file at the
top-level directory of this distribution and at <https://github.com/Ulm-IQO/qudi/>
"""

import numpy as np
import PyDAQmx as daq
import re

from core.module import Base, StatusVar, ConfigOption
from interface.slow_counter_interface import SlowCounterInterface
from interface.slow_counter_interface import SlowCounterConstraints
from interface.slow_counter_interface import CountingMode
from interface.confocal_scanner_interface import ConfocalScannerInterface
from interface.odmr_counter_interface import ODMRCounterInterface
from interface.analog_control_interface import AnalogControlInterface


class NI6229Card(Base, SlowCounterInterface, ConfocalScannerInterface,
                 ODMRCounterInterface):
    """ unstable: Alexander Stark

    Tested for the Hardware card NI 6229
    A hardware based counting procedure.

    An example configuration for the hardware module might look like:

    nicard6229:
        module.Class: 'ni_6229_card.NI6229Card'
        clock_channel: '/Dev2/Ctr1'
        counter_channel: '/Dev2/Ctr0'
        clock_frequency: 100 # in Hz; independent of clock_frequency
        scanner_clock_channel: '/Dev2/Ctr1'
        scanner_counter_channel: '/Dev2/Ctr0'
        scanner_clock_frequency: 100 # in Hz; independent of clock_frequency
        photon_source: '/Dev2/PFI8' # which should be '/Dev2/Ctr0'
        trigger_channel: '/Dev2/Ctr1' # this will be '/Dev2/PFI13'
        odmr_clock_channel: '/Dev2/Ctr1'
        odmr_counter_channel: '/Dev2/Ctr0'
        odmr_clock_frequency: 50    # in Hz
        scanner_x_ao: '/Dev2/AO0'
        scanner_y_ao: '/Dev2/AO1'
        scanner_z_ao: '/Dev2/AO2'
        samples_number: 50
        read_write_timeout: 10  #in s
        counting_edge_rising: True
        x_range:
           - -25e-6
           - 25e-6   # in Micrometers
        y_range:
            - -25e-6
            - 25e-6 # in Micrometers
        z_range:
            - -14e-6
            - 14e-6 # in Micrometers
        voltage_x_range:
            - 0
            - 8
        voltage_y_range:
            - 0
            - 8
        voltage_z_range:
            - 0
            - 8

    """

    _modtype = 'NI6229Card'
    _modclass = 'hardware'

    # config options
    # serves in the same time as
    _clock_channel = ConfigOption('clock_channel', missing='error')
    _counter_channel = ConfigOption('counter_channel', missing='error')
    _clock_frequency = ConfigOption('clock_frequency', 100, missing='warn')  # in Hz

    _scanner_clock_channel = ConfigOption('scanner_clock_channel', missing='error')
    _scanner_counter_channel = ConfigOption('scanner_counter_channel', missing='error')
    _scanner_clock_frequency = ConfigOption('scanner_clock_frequency', 100, missing='warn')  # in Hz

    _photon_source = ConfigOption('photon_source', missing='error')
    # in the case of just two counter, the trigger channel equals the clock channel.
    _trigger_channel = ConfigOption('trigger_channel', missing='error')

    _odmr_clock_channel = ConfigOption('odmr_clock_channel', missing='error')
    _odmr_counter_channel = ConfigOption('odmr_counter_channel', missing='error')
    _odmr_clock_frequency = ConfigOption('odmr_clock_frequency', 100, missing='warn')  # in Hz

    _scanner_x_ao = ConfigOption('scanner_x_ao', missing='error')
    _scanner_y_ao = ConfigOption('scanner_y_ao', missing='error')
    _scanner_z_ao = ConfigOption('scanner_z_ao', missing='error')

    # how many samples per request are obtained in continuous counting.
    _samples_number = ConfigOption('samples_number', 50, missing='warn')
    # used as a default for expected maximum counts
    _max_counts = ConfigOption('max_counts', 3e7)
    # timeout for the Read or/and write process in s
    _RWTimeout = ConfigOption('read_write_timeout', 10)
    # set how the clock is reacting
    _counting_edge_rising = ConfigOption('counting_edge_rising', True, missing='warn')

    _x_range = ConfigOption('x_range', missing='error')  # in m
    _y_range = ConfigOption('y_range', missing='error')  # in m
    _z_range = ConfigOption('z_range', missing='error')  # in m

    _voltage_x_range = ConfigOption('voltage_x_range', missing='error')  # in V
    _voltage_y_range = ConfigOption('voltage_y_range', missing='error')  # in V
    _voltage_z_range = ConfigOption('voltage_z_range', missing='error')  # in V

    def on_activate(self):
        """ Starts up the NI Card at activation. """

        # initialize all the task variables
        self._clock_daq_task = None
        self._counter_daq_task = None

        self._scanner_clock_daq_task = None
        self._scanner_ao_task = None
        self._scanner_counter_daq_task = None

        self._odmr_clock_daq_task = None
        self._odmr_counter_daq_task = None

        self._odmr_length = 100

        self._line_length = 100
        self._scanner_ao_channels = [self._scanner_x_ao, self._scanner_y_ao,
                                     self._scanner_z_ao]
        self._voltage_range = [self._voltage_x_range, self._voltage_y_range,
                               self._voltage_z_range]

        self._position_range = [self._x_range, self._y_range, self._z_range]

        self._current_position = [0, 0, 0]

        # Analog output is always needed and it does not interfere with the
        # rest, so start it always and leave it running
        if self._start_analog_output() < 0:
            self.log.error('Failed to start analog output.')
            raise Exception('Failed to start NI Card module due to analog output failure.')

    def on_deactivate(self):
        """ Shut down the NI card.
        """
        self.reset_hardware()

    # =================== SlowCounterInterface Commands ========================

    def get_constraints(self):
        """ Get hardware limits of NI device.

        @return SlowCounterConstraints: constraints class for slow counter

        FIXME: ask hardware for limits when module is loaded
        """
        constraints = SlowCounterConstraints()
        constraints.max_detectors = 1
        constraints.min_count_frequency = 1e-3
        constraints.max_count_frequency = 10e9
        constraints.counting_mode = [CountingMode.CONTINUOUS]
        return constraints

    def set_up_clock(self, clock_frequency=None, clock_channel=None,
                     idle=False):
        """ Configures the hardware clock of the NiDAQ card to give the timing.

        @param float clock_frequency: optional, if defined, this sets the
                                      frequency of the clock in Hz
        @param str clock_channel: optional, if defined, this is the physical
                                  channel of the clock within the NI card.
        @param bool idle: optional, set whether idle situation of the counter
                         (where counter is doing nothing) is defined as
                            True  = 'Voltage High/Rising Edge'
                            False = 'Voltage Low/Falling Edge'

        @return int: error code (0:OK, -1:error)
        """

        if self._clock_daq_task is not None:
            self.log.error('Another counter clock is already running, close '
                           'this one first.')
            return -1

        # check whether only one clock pair is available, since in some NI cards
        # (e.g. M-series) only one clock channel pair can be used.
        if self._scanner_clock_daq_task is not None:
            self.log.error('Only one clock channel is available!\n'
                           'Another clock is already running, close this one '
                           'first in order to use it for your purpose!')
            return -1

        # Create handle for task, this task will generate pulse signal for
        # photon counting
        self._clock_daq_task = daq.TaskHandle()

        # assign the clock frequency, if given
        if clock_frequency is not None:
            self._clock_frequency = float(clock_frequency)

        # assign the clock channel, if given
        if clock_channel is not None:
            curr_clock_ch = clock_channel
        else:
            curr_clock_ch = self._clock_channel

        # Adjust the idle state if necessary
        my_idle = daq.DAQmx_Val_High if idle else daq.DAQmx_Val_Low
        try:
            # create task for clock
            task_name = 'CounterClock'
            daq.DAQmxCreateTask(task_name, daq.byref(self._clock_daq_task))

            # create a digital clock channel with specific clock frequency:
            daq.DAQmxCreateCOPulseChanFreq(
                # The task to which to add the channels
                self._clock_daq_task,
                # which channel is used?
                curr_clock_ch,
                # Name to assign to task (NIDAQ uses by # default the physical channel name as
                # the virtual channel name. If name is specified, then you must use the name
                # when you refer to that channel in other NIDAQ functions)
                'Clock Producer',
                # units, Hertz in our case
                daq.DAQmx_Val_Hz,
                # idle state
                my_idle,
                # initial delay
                0,
                # pulse frequency, divide by 2 such that length of semi period = count_interval
                self._clock_frequency / 2,
                # duty cycle of pulses, 0.5 such that high and low duration are both
                # equal to count_interval
                0.5)

            # Configure Implicit Timing.
            # Set timing to continuous, i.e. set only the number of samples to
            # acquire or generate without specifying timing:
            daq.DAQmxCfgImplicitTiming(
                # Define task
                self._clock_daq_task,
                # Sample Mode: set the task to generate a continuous amount of running samples
                daq.DAQmx_Val_ContSamps,
                # buffer length which stores temporarily the number of generated samples
                10000)

            # actually start the preconfigured clock task
            daq.DAQmxStartTask(self._clock_daq_task)

        except:
            self.log.exception('Error while setting up Counter clock.')
            return -1

        self.log.info('Clock Started.')

        return 0

    def set_up_counter(self, counter_channels=None, sources=None,
                       clock_channel=None, counter_buffer=None):
        """ Configures the actual counter with a given clock.

        @param list(str) counter_channels: optional, physical channel of the counter
        @param list(str) sources: optional, physical channel where the photons
                                   photons are to count from
        @param str clock_channel: optional, specifies the clock channel for the
                                  counter
        @param int counter_buffer: optional, a buffer of specified integer
                                   length, where in each bin the count numbers
                                   are saved.

        @return int: error code (0:OK, -1:error)

        There need to be exactly the same number of sources and counter channels
        and they need to be given in the same order.
        All counter channels share the same clock.
        """

        if self._clock_daq_task is None and clock_channel is None:
            self.log.error('No clock running, call set_up_clock before '
                           'starting the counter!')
            return -1

        if self._counter_daq_task is not None or self._scanner_counter_daq_task is not None:
            self.log.error('Another counter is already running, close this one '
                           'first.')
            return -1

        # in order to make it interface compatible, a list can be passed, but
        # for the M-series card only the first channel will be taken!
        if counter_channels is not None:
            curr_counter_ch = counter_channels[0]
        else:
            curr_counter_ch = self._counter_channel

        if sources is not None:
            curr_photon_source = sources[0]
        else:
            curr_photon_source = self._photon_source

        if clock_channel is not None:
            curr_clock_channel = clock_channel
        else:
            curr_clock_channel = self._clock_channel

        try:
            # This task will count photons with binning defined by the clock_channel
            self._counter_daq_task = daq.TaskHandle()  # Initialize a Task
            # Create task for the counter
            taskname = 'CounterTask'
            daq.DAQmxCreateTask(taskname, daq.byref(self._counter_daq_task))
            # Create a Counter Input which samples with Semi-Periodes the Channel.
            # set up semi period width measurement in photon ticks, i.e. the width
            # of each pulse (high and low) generated by pulse_out_task is measured
            # in photon ticks.
            #   (this task creates a channel to measure the time between state
            #    transitions of a digital signal and adds the channel to the task
            #    you choose)
            daq.DAQmxCreateCISemiPeriodChan(
                # define to which task to connect this function
                self._counter_daq_task,
                # use this counter channel
                curr_counter_ch,
                # name to assign to it
                'Counter Channel',
                # expected minimum count value
                0,
                # Expected maximum count value
                self._max_counts / 2 / self._clock_frequency,
                # units of width measurement, here photon ticks
                daq.DAQmx_Val_Ticks,
                # empty extra argument
                '')

            # Set the Counter Input to a Semi Period input Terminal.
            # Connect the pulses from the counter clock to the counter channel
            daq.DAQmxSetCISemiPeriodTerm(
                # The task to which to add the counter channel.
                self._counter_daq_task,
                # use this counter channel
                curr_counter_ch,
                # assign a named Terminal
                curr_clock_channel + 'InternalOutput')

            # Set a Counter Input Control Timebase Source.
            # Specify the terminal of the timebase which is used for the counter:
            # Define the source of ticks for the counter as self._photon_source for
            # the Scanner Task.
            daq.DAQmxSetCICtrTimebaseSrc(
                # define to which task to connect this function
                self._counter_daq_task,
                # counter channel
                curr_counter_ch,
                # counter channel to output the counting results
                curr_photon_source)

            # Configure Implicit Timing.
            # Set timing to continuous, i.e. set only the number of samples to
            # acquire or generate without specifying timing:
            daq.DAQmxCfgImplicitTiming(
                # define to which task to connect this function
                self._counter_daq_task,
                # Sample Mode: Acquire or generate samples until you stop the task.
                daq.DAQmx_Val_ContSamps,
                # buffer length which stores  temporarily the number of generated samples
                1000)

            # Set the Read point Relative To an operation.
            # Specifies the point in the buffer at which to begin a read operation.
            # Here we read most recent recorded samples:
            daq.DAQmxSetReadRelativeTo(
                # define to which task to connect this function
                self._counter_daq_task,
                # Start reading samples relative to the last sample returned by the previously.
                daq.DAQmx_Val_CurrReadPos)

            # Set the Read Offset.
            # Specifies an offset in samples per channel at which to begin a read
            # operation. This offset is relative to the location you specify with
            # RelativeTo. Here we set the Offset to 0 for multiple samples:
            daq.DAQmxSetReadOffset(self._counter_daq_task, 0)

            # Set Read OverWrite Mode.
            # Specifies whether to overwrite samples in the buffer that you have
            # not yet read. Unread data in buffer will be overwritten:
            daq.DAQmxSetReadOverWrite(
                self._counter_daq_task,
                daq.DAQmx_Val_DoNotOverwriteUnreadSamps)

        except:
            self.log.exception('Error while setting up counting task.')
            return -1

        try:
            daq.DAQmxStartTask(self._counter_daq_task)
        except:
            self.log.exception('Error while starting Counter.')
            try:
                self.close_counter()
            except:
                self.log.exception('Could not close counter after error')
            return -1

        return 0

    def get_counter_channels(self):
        """ Returns the list of counter channel names.

        @return list(str): channel names

        Most methods calling this might just care about the number of channels, though.
        """
        return [self._counter_channel]

    def get_counter(self, samples=None):
        """ Returns the current counts per second of the counter.

        @param int samples: optional, if defined, number of samples to read in
                            one go. How many samples are read per readout cycle.
                            The readout frequency was defined in the counter
                            setup. That sets also the length of the readout
                            array.

        @return numpy.array((n, uint32)): the photon counts per second for n
                                          channels
        """

        if self._counter_daq_task is None:
            self.log.error(
                'No counter running, call set_up_counter before reading it.')
            # in case of error return a lot of -1
            return np.ones((len(self.get_counter_channels()), samples),
                           dtype=np.uint32) * -1

        if samples is None:
            samples = int(self._samples_number)
        else:
            samples = int(samples)
        try:
            # count data will be written here in the NumPy array of length samples
            # there will be just one task!
            count_data = np.empty((len([self._counter_daq_task]), samples),
                                  dtype=np.uint32)

            # number of samples which were actually read, will be stored here
            n_read_samples = daq.int32()
            for i, task in enumerate([self._counter_daq_task]):
                # read the counter value: This function is blocking and waits for the
                # counts to be all filled:
                daq.DAQmxReadCounterU32(
                    # read from this task
                    task,
                    # number of samples to read
                    samples,
                    # maximal timeout for the read process
                    self._RWTimeout,
                    # write the readout into this array
                    count_data[i],
                    # length of array to write into
                    samples,
                    # number of samples which were read
                    daq.byref(n_read_samples),
                    # Reserved for future use. Pass NULL (here None) to this parameter
                    None)
        except:
            self.log.exception(
                'Getting samples from counter failed.')
            # in case of error return a lot of -1
            return np.ones((len(self.get_counter_channels()), samples), dtype=np.uint32) * -1
        # normalize to counts per second and return data
        return count_data * self._clock_frequency

    def close_counter(self):
        """ Close the counter and clean up afterwards.

        @return int: error code (0:OK, -1:error)
        """

        error = 0
        try:
            # stop the counter task
            daq.DAQmxStopTask(self._counter_daq_task)
            # after stopping delete all the configuration of the counter
            daq.DAQmxClearTask(self._counter_daq_task)
            # set the task handle to None as a safety
        except:
            self.log.exception('Could not close counter.')
            error = -1

        self._counter_daq_task = None
        return error

    def close_clock(self):
        """ Closes the clock and cleans up afterwards.

        @return int: error code (0:OK, -1:error)
        """

        try:
            # Stop the clock task:
            daq.DAQmxStopTask(self._clock_daq_task)

            # After stopping delete all the configuration of the clock:
            daq.DAQmxClearTask(self._clock_daq_task)

            # Set the task handle to None as a safety
            self._clock_daq_task = None

        except:
            self.log.exception('Could not close clock.')
            return -1

        return 0

    # ================ End SlowCounterInterface Commands =======================

    # ================ ConfocalScannerInterface Commands =======================

    def reset_hardware(self):
        """ Resets the NI hardware, so the connection is lost and other
            programs can access it.

        @return int: error code (0:OK, -1:error)
        """
        retval = 0

        # combine all the used channels to obtain all the used devices so that
        # the reset will act on all devices. (Usually just one device is used.)
        chanlist = [self._trigger_channel,
                    self._clock_channel,
                    self._scanner_clock_channel,
                    self._scanner_counter_channel,
                    self._photon_source,
                    self._scanner_x_ao,
                    self._scanner_y_ao,
                    self._scanner_z_ao]

        devicelist = []
        for channel in chanlist:
            if channel is None:
                continue
            match = re.match(
                '^/(?P<dev>[0-9A-Za-z\- ]+[0-9A-Za-z\-_ ]*)/(?P<chan>[0-9A-Za-z]+)',
                channel)
            if match:
                devicelist.append(match.group('dev'))
            else:
                self.log.error('Did not find device name in {0}.'.format(channel))

        # reset all the used devices
        for device in set(devicelist):
            try:
                daq.DAQmxResetDevice(device)  # device should be something like 'Dev1' or 'Dev2'
                self.log.info('Reset device {0}.'.format(device))
            except:
                self.log.exception('Could not reset NI device {0}'.format(device))
                retval = -1
        return retval

    def get_scanner_axes(self):
        """ Scanner axes depends on how many channels tha analog output task has.
        """
        if self._scanner_ao_task is None:
            self.log.error('Cannot get channel number, analog output task does not exist.')
            return []

        n_channels = daq.uInt32()
        daq.DAQmxGetTaskNumChans(self._scanner_ao_task, n_channels)
        possible_channels = ['x', 'y', 'z', 'a']

        return possible_channels[0:int(n_channels.value)]

    def get_scanner_count_channels(self):
        """ Return list of counter channels """
        return [self._scanner_counter_channel]

    def get_position_range(self):
        """ Returns the physical range of the scanner.

        @return float [4][2]: array of 4 ranges with an array containing lower
                              and upper limit. The unit of the scan range is
                              meters.
        """
        # the last axis is not used, therefore set ranges just to zero
        return [self._x_range, self._y_range, self._z_range, [0, 0]]

    def set_position_range(self, myrange=None):
        """ Sets the physical range of the scanner.

        @param float [4][2] myrange: array of 4 ranges with an array containing
                                     lower and upper limit. The unit of the
                                     scan range is meters.

        @return int: error code (0:OK, -1:error)
        """
        if myrange is None:
            self.log.error('No position range passed. Skip range setting.')
            return 0

        if not isinstance(myrange, (frozenset, list, set, tuple, np.ndarray,)):
            self.log.error('Given range is no array type.')
            return -1

        if len(myrange) != 4:
            self.log.error('Given range should have dimension 4, but has {0:d} '
                           'instead.'.format(len(myrange)))
            return -1

        for pos in myrange:
            if len(pos) != 2:
                self.log.error('Given range limit {1:d} should have dimension '
                               '2, but has {0:d} instead.'
                               ''.format(len(pos), pos))
                return -1

            if pos[0] > pos[1]:
                self.log.error('Given range limit {0:d} has the wrong order.'
                               ''.format(pos))
                return -1

        self._position_range = myrange
        return 0

    def set_voltage_range(self, myrange=None):
        """ Sets the voltage range of the NI Card.

        @param float [n][2] myrange: array containing lower and upper limit

        @return int: error code (0:OK, -1:error)
        """
        n_ch = len(self.get_scanner_axes())

        if myrange is None:
            self.log.error('No Voltage range passed. Skip range setting.')
            return 0

        if not isinstance(myrange, (frozenset, list, set, tuple, np.ndarray)):
            self.log.error('Given range is no array type.')
            return -1

        if len(myrange) != n_ch:
            self.log.error('Given range should have dimension 2, but has {0:d} '
                           'instead.'.format(len(myrange)))
            return -1

        for r in myrange:
            if r[0] > r[1]:
                self.log.error('Given range limit {0:d} has the wrong '
                               'order.'.format(r))
                return -1

        self._voltage_range = myrange
        return 0

    def _start_analog_output(self):
        """ Starts or restarts the analog output.

        @return int: error code (0:OK, -1:error)
        """
        try:
            # If an analog task is already running, kill that one first
            if self._scanner_ao_task is not None:
                # stop the analog output task
                daq.DAQmxStopTask(self._scanner_ao_task)

                # delete the configuration of the analog output
                daq.DAQmxClearTask(self._scanner_ao_task)

                # set the task handle to None as a safety
                self._scanner_ao_task = None

            # initialize ao channels / task for scanner, should always be active.
            # Define at first the type of the variable as a Task:
            self._scanner_ao_task = daq.TaskHandle()

            # create the actual analog output task on the hardware device. Via
            # byref you pass the pointer of the object to the TaskCreation function:
            daq.DAQmxCreateTask('ScannerAO', daq.byref(self._scanner_ao_task))
            for n, chan in enumerate(self._scanner_ao_channels):
                # Assign and configure the created task to an analog output voltage channel.
                daq.DAQmxCreateAOVoltageChan(
                    # The AO voltage operation function is assigned to this task.
                    self._scanner_ao_task,
                    # use (all) scanner ao_channels for the output
                    chan,
                    # assign a name for that channel
                    'Scanner AO Channel {0}'.format(n),
                    # minimum possible voltage
                    self._voltage_range[n][0],
                    # maximum possible voltage
                    self._voltage_range[n][1],
                    # units is Volt
                    daq.DAQmx_Val_Volts,
                    # empty for future use
                    '')
        except:
            self.log.exception('Error starting analog output task.')
            return -1
        return 0

    def _stop_analog_output(self):
        """ Stops the analog output.

        @return int: error code (0:OK, -1:error)
        """
        if self._scanner_ao_task is None:
            return -1
        retval = 0

        try:
            # stop the analog output task
            daq.DAQmxStopTask(self._scanner_ao_task)
        except:
            self.log.exception('Error stopping analog output.')
            retval = -1
        try:
            daq.DAQmxSetSampTimingType(self._scanner_ao_task, daq.DAQmx_Val_OnDemand)
        except:
            self.log.exception('Error changing analog output mode.')
            retval = -1
        return retval

    def set_up_scanner_clock(self, clock_frequency=None, clock_channel=None,
                             idle=False):
        """ Configures the hardware clock of the NiDAQ card to give the timing.

        @param float clock_frequency: optional, if defined, this sets the
                                      frequency of the clock
        @param str clock_channel: optional, if defined, this is the physical
                                  channel of the clock
        @param bool idle: set whether idle situation of the counter (where
                          counter is doing nothing) is defined as
                            True  = 'Voltage High/Rising Edge'
                            False = 'Voltage Low/Falling Edge'

        @return int: error code (0:OK, -1:error)
        """
        # The clock for the scanner is created on the same principle as it is
        # for the counter. Just to keep consistency, this function is a wrapper
        # around the set_up_clock.

        if self._scanner_clock_daq_task is not None:
            self.log.error('Another scanner counter clock is already running, '
                           'close this one first.')
            return -1

        # check whether only one clock pair is available, since in some NI cards
        # (e.g. M-series) only one clock channel pair can be used.
        if self._clock_daq_task is not None:
            self.log.error('Only one clock channel is available!\n'
                           'Another counter clock is already running, close '
                           'this one first in order to use it for your '
                           'purpose!')
            return -1

        # Create handle for task, this task will generate pulse signal for
        # photon counting
        self._scanner_clock_daq_task = daq.TaskHandle()

        # assign the clock frequency, if given
        if clock_frequency is not None:
            self._scanner_clock_frequency = float(clock_frequency)

        # assign the clock channel, if given
        if clock_channel is not None:
            curr_clock_ch = clock_channel
        else:
            curr_clock_ch = self._scanner_clock_channel

        # Adjust the idle state if necessary
        my_idle = daq.DAQmx_Val_High if idle else daq.DAQmx_Val_Low

        try:
            # Create the Task here:
            task_name = 'ScannerClock'
            daq.DAQmxCreateTask(task_name, daq.byref(self._scanner_clock_daq_task))

            daq.DAQmxCreateCOPulseChanFreq(
                # The task to which to add the channels
                self._scanner_clock_daq_task,
                # which channel is used?
                curr_clock_ch,
                # Name to assign to task (NIDAQ uses by # default the physical channel name as
                # the virtual channel name. If name is specified, then you must use the name
                # when you refer to that channel in other NIDAQ functions)
                'Scanner Clock Producer',
                # units, Hertz in our case
                daq.DAQmx_Val_Hz,
                # idle state
                my_idle,
                # initial delay
                0,
                # pulse frequency, divide by 2 such that length of semi period = count_interval
                self._scanner_clock_frequency / 2,
                # duty cycle of pulses, 0.5 such that high and low duration are both
                # equal to count_interval
                0.5)

            daq.DAQmxCfgImplicitTiming(
                # Define task
                self._scanner_clock_daq_task,
                # Sample Mode: set the task to generate a continuous amount of running samples
                daq.DAQmx_Val_ContSamps,
                # buffer length which stores temporarily the number of generated samples
                10000)

        except:
            self.log.exception('Error while setting up scanner clock.')
            return -1
        return 0

    def set_up_scanner(self, counter_channels=None, sources=None,
                       clock_channel=None, scanner_ao_channels=None):
        """ Configures the actual scanner with a given clock.

        The scanner works pretty much like the counter. Here you connect a
        created clock with a counting task. That can be seen as a gated
        counting, where the counts where sampled by the underlying clock.

        @param list(str) counter_channels: this is the physical channel of the counter
        @param list(str) sources:  this is the physical channel where the photons are to count from
        @param string clock_channel: optional, if defined, this specifies the clock for the counter
        @param list(str) scanner_ao_channels: optional, if defined, this specifies
                                           the analog output channels

        @return int: error code (0:OK, -1:error)
        """

        if self._scanner_clock_daq_task is None and clock_channel is None:
            self.log.error('No clock running, call set_up_clock before '
                           'starting the counter!')
            return -1

        if self._scanner_counter_daq_task is not None or self._counter_daq_task is not None:
            self.log.error('Another counter is already running, close this one '
                           'first.')
            return -1

        # in order to make it interface compatible, a list can be passed, but
        # for the M-series card only the first channel will be taken!
        if counter_channels is not None:
            curr_counter_ch = counter_channels[0]
        else:
            curr_counter_ch = self._scanner_counter_channel

        if sources is not None:
            curr_photon_source = sources[0]
        else:
            curr_photon_source = self._photon_source

        if clock_channel is not None:
            curr_clock_channel = clock_channel
        else:
            curr_clock_channel = self._scanner_clock_channel

        if scanner_ao_channels is not None:
            self._scanner_ao_channels = scanner_ao_channels
            retval = self._start_analog_output()

        try:
            # This task will count photons with binning defined by the clock_channel
            self._scanner_counter_daq_task = daq.TaskHandle()  # Initialize a Task
            # Create task for the counter
            taskname = 'ScannerCounterTask'
            daq.DAQmxCreateTask(taskname, daq.byref(self._scanner_counter_daq_task))

            daq.DAQmxCreateCICountEdgesChan(
                self._scanner_counter_daq_task,
                # assign a counter channel
                curr_counter_ch,
                # nameToAssignToChannel
                'Counter In',
                # specify the edge
                daq.DAQmx_Val_Rising,
                # The value from which to start counting
                0,
                # Specifies whether to increment or decrement the counter on each edge.
                daq.DAQmx_Val_CountUp)

        except:
            self.log.exception('Error while setting up scanner counting task.')
            return -1

        return 0

    def scanner_set_position(self, x=None, y=None, z=None, a=None):
        """Move stage to x, y, z, a (where a is the fourth voltage channel).

        #FIXME: No volts
        @param float x: postion in x-direction (volts)
        @param float y: postion in y-direction (volts)
        @param float z: postion in z-direction (volts)
        @param float a: postion in a-direction (volts)

        @return int: error code (0:OK, -1:error)
        """

        if self.getState() == 'locked':
            self.log.error('Another scan_line is already running, close this one first.')
            return -1

        if x is not None:
            if not (self._position_range[0][0] <= x <= self._position_range[0][1]):
                self.log.error('You want to set x out of range: {0:f}.'.format(x))
                return -1
            self._current_position[0] = np.float(x)

        if y is not None:
            if not (self._position_range[1][0] <= y <= self._position_range[1][1]):
                self.log.error('You want to set y out of range: {0:f}.'.format(y))
                return -1
            self._current_position[1] = np.float(y)

        if z is not None:
            if not (self._position_range[2][0] <= z <= self._position_range[2][1]):
                self.log.error('You want to set z out of range: {0:f}.'.format(z))
                return -1
            self._current_position[2] = np.float(z)

        if a is not None:
            if not (self._position_range[3][0] <= a <= self._position_range[3][1]):
                self.log.error('You want to set a out of range: {0:f}.'.format(a))
                return -1
            self._current_position[3] = np.float(a)

        # the position has to be a vstack
        my_position = np.vstack(self._current_position)

        # then directly write the position to the hardware
        try:
            self._write_scanner_ao(
                voltages=self._scanner_position_to_volt(my_position),
                start=True)
        except:
            return -1
        return 0

    def get_scanner_position(self):
        """ Get the current position of the scanner hardware.

        @return float[]: current position in (x, y, z, a).
        """
        return self._current_position

    def _set_up_line(self, length=100):
        """ Sets up the analog output for scanning a line.

        Connect the timing of the Analog scanning task with the timing of the
        counting task.

        @param int length: length of the line in pixel

        @return int: error code (0:OK, -1:error)
        """
        if self._scanner_counter_daq_task is None:
            self.log.error('No scanner counter is running, cannot scan a line '
                           'without one.')
            return -1

        self._line_length = length

        try:
            # Set up the necessary parts for the Counter In Task
            daq.DAQmxCfgSampClkTiming(
                # add to this task
                self._scanner_counter_daq_task,
                # use this channel as clock
                self._scanner_clock_channel + 'InternalOutput',
                # Maximum expected clock frequency
                self._scanner_clock_frequency,
                # Generate sample on falling edge
                daq.DAQmx_Val_Rising,
                # generate finite number of samples
                daq.DAQmx_Val_FiniteSamps,
                # number of samples to generate +2 (first one is used to
                # start/trigger the tasks related to the clock and make one
                # more for safety)
                self._line_length + 2)

            # Set up the necessary parts for the Analog Out Task
            daq.DAQmxCfgSampClkTiming(
                # add to this task
                self._scanner_ao_task,
                # use this channel as clock
                self._scanner_clock_channel + 'InternalOutput',
                # Maximum expected clock frequency
                self._scanner_clock_frequency,
                # Generate sample on falling edge
                daq.DAQmx_Val_Rising,  # daq.DAQmx_Val_Falling
                # generate finite number of samples
                daq.DAQmx_Val_FiniteSamps,
                # number of samples to generate, here the exact number of
                # voltages need to be specified, otherwise the scanner will jump
                self._line_length)

        except:
            self.log.exception('Error while setting up scanner to scan a line.')
            return -1

        return 0

    def scan_line(self, line_path=None, pixel_clock=False):
        """ Scans a line and return the counts on that line.

        @param float[c][m] line_path: array of c-tuples defining the voltage points
            (m = samples per line)
        @param bool pixel_clock: whether we need to output a pixel clock for this line

        @return float[m][n]: m (samples per line) n-channel photon counts per second

        The input array looks for a xy scan of 5x5 points at the position z=-2
        like the following:
            [ [1, 2, 3, 4, 5], [1, 1, 1, 1, 1], [-2, -2, -2, -2] ]
        n is the number of scanner axes, which can vary. Typical values are 2 for galvo scanners,
        3 for xyz scanners and 4 for xyz scanners with a special function on the a axis.
        """

        if self._scanner_counter_daq_task is None:
            self.log.error('No scanner counter is running, cannot scan a line '
                           'without one.')
            return np.array([[-1.]])

        if not isinstance(line_path, (frozenset, list, set, tuple, np.ndarray,)):
            self.log.error('Given line_path list is not array type.')
            return np.array([[-1.]])

        try:

            # set task timing to use a sampling clock:
            # specify how the Data of the selected task is collected, i.e. set it
            # now to be sampled by a hardware (clock) signal.

            # #TODO: Is that needed here??? ==> We will test that
            daq.DAQmxSetSampTimingType(self._scanner_ao_task, daq.DAQmx_Val_SampClk)

            self._set_up_line(np.shape(line_path)[1])
            line_volts = self._scanner_position_to_volt(line_path)
            # write the positions to the analog output
            written_voltages = self._write_scanner_ao(
                voltages=line_volts,
                length=self._line_length,
                start=False)

            # start the timed analog output task
            daq.DAQmxStartTask(self._scanner_ao_task)

            # stop any ongoing counter and clock tasks just to be save.
            # daq.DAQmxStopTask(self._scanner_counter_daq_task)
            # daq.DAQmxStopTask(self._scanner_clock_daq_task)

            # if pixel_clock and self._pixel_clock_channel is not None:
            #     daq.DAQmxConnectTerms(
            #         self._scanner_clock_channel + 'InternalOutput',
            #         self._pixel_clock_channel,
            #         daq.DAQmx_Val_DoNotInvertPolarity)

            # start the scanner counting task that acquires counts
            # synchroneously
            daq.DAQmxStartTask(self._scanner_counter_daq_task)

            # this last task starts the whole process of data
            daq.DAQmxStartTask(self._scanner_clock_daq_task)

            # wait for the scanner counter to finish
            daq.DAQmxWaitUntilTaskDone(
                # define task
                self._scanner_counter_daq_task,
                # Maximum timeout for the counter times the positions. Unit is seconds.
                self._RWTimeout * 2 * self._line_length)

            # wait that analog output is finished
            daq.DAQmxWaitUntilTaskDone(
                # define task
                self._scanner_ao_task,
                # maximal timeout for the counter times the positions
                self._RWTimeout * 2 * self._line_length)

            # count data will be stored here, allocated place. Count two more,
            # since first count will not have information in it but just start
            # the counting process and it is necessary to count +1 longer,
            # since the last point in the array is zero and the count value is
            # not written to the last array element, because task ended before
            # that.
            self._scan_data = np.zeros(
                (len(self.get_scanner_count_channels()), self._line_length + 2),
                dtype=np.uint32)

            # available_samples = daq.uInt32()
            # daq.DAQmxGetReadAvailSampPerChan(self._scanner_counter_daq_task,
            #                                  available_samples)

            # number of samples which were read will be stored here
            n_read_samples = daq.int32()

            # actually read the counted photons
            daq.DAQmxReadCounterU32(
                # read from this task
                self._scanner_counter_daq_task,
                # read number of double the # number of samples
                self._line_length + 2,
                # maximal timeout for the read# process
                self._RWTimeout,
                # write into this array
                self._scan_data[0],
                # length of array to write into
                self._line_length + 2,
                # number of samples which were actually read
                daq.byref(n_read_samples),
                # Reserved for future use. Pass NULL(here None) to this parameter.
                None)

            # stop the counter task
            daq.DAQmxStopTask(self._scanner_counter_daq_task)

            # stop the analog output task
            self._stop_analog_output()

            # stop the clock task
            daq.DAQmxStopTask(self._scanner_clock_daq_task)

            # if pixel_clock and self._pixel_clock_channel is not None:
            #     daq.DAQmxDisconnectTerms(
            #         self._scanner_clock_channel + 'InternalOutput',
            #         self._pixel_clock_channel)

            # create a new array for the final data (this time of the length
            # number of samples):
            self._real_data = np.empty(
                (len(self.get_scanner_count_channels()), self._line_length),
                dtype=np.uint32)

            # the counts are counted up and the current value is saved to the
            # current array index. To get the actual size of an entry the
            # previous value has to be subtracted.
            previous = self._scan_data[0][0]
            for index, entry in enumerate(self._scan_data[0][1:-1]):
                self._real_data[0][index] = entry - previous
                previous = entry

            # add up adjoint pixels to also get the counts from the low time of
            # the clock:
            # self._real_data = self._scan_data[:, ::2]
            # self._real_data += self._scan_data[:, 1::2]

            # update the scanner position instance variable
            self._current_position = list(line_path[:, -1])

        except:
            self.log.exception('Error while scanning line.')
            return np.array([[-1.]])

        # return values is a rate of counts/s
        return (self._real_data * self._scanner_clock_frequency / 2).transpose()

    def _scanner_position_to_volt(self, positions=None):
        """ Converts a set of position pixels to acutal voltages.

        @param float[][n] positions: array of n-part tuples defining the pixels

        @return float[][n]: array of n-part tuples of corresponing voltages

        The positions is typically a matrix like
            [[x_values], [y_values], [z_values], [a_values]]
            but x, xy, xyz and xyza are allowed formats.
        """

        if not isinstance(positions, (frozenset, list, set, tuple, np.ndarray,)):
            self.log.error('Given position list is no array type.')
            return np.array([np.NaN])

        vlist = []
        for i, position in enumerate(positions):
            vlist.append(
                (self._voltage_range[i][1] - self._voltage_range[i][0])
                / (self._position_range[i][1] - self._position_range[i][0])
                * (position - self._position_range[i][0])
                + self._voltage_range[i][0]
            )
        volts = np.vstack(vlist)

        for i, v in enumerate(volts):
            if v.min() < self._voltage_range[i][0] or v.max() > self._voltage_range[i][1]:
                self.log.error(
                    'Voltages ({0}, {1}) exceed the limit, the positions have to '
                    'be adjusted to stay in the given range.'.format(v.min(), v.max()))
                return np.array([np.NaN])
        return volts

    def _write_scanner_ao(self, voltages, length=1, start=False):
        """Writes a set of voltages to the analog outputs.

        @param float[][n] voltages: array of n-part tuples defining the voltage
                                    points
        @param int length: number of tuples to write
        @param bool start: write imediately (True)
                           or wait for start of task (False)

        n depends on how many channels are configured for analog output
        """
        # Number of samples which were actually written, will be stored here.
        # The error code of this variable can be asked with .value to check
        # whether all channels have been written successfully.
        self._AONwritten = daq.int32()
        # write the voltage instructions for the analog output to the hardware
        daq.DAQmxWriteAnalogF64(
            # write to this task
            self._scanner_ao_task,
            # length of the command (points)
            length,
            # start task immediately (True), or wait for software start (False)
            start,
            # maximal timeout in seconds for# the write process
            self._RWTimeout,
            # Specify how the samples are arranged: each pixel is grouped by channel number
            daq.DAQmx_Val_GroupByChannel,
            # the voltages to be written
            voltages,
            # The actual number of samples per channel successfully written to the buffer
            daq.byref(self._AONwritten),
            # Reserved for future use. Pass NULL(here None) to this parameter
            None)
        return self._AONwritten.value

    def close_scanner(self):
        """ Closes the scanner and cleans up afterwards.

        @return int: error code (0:OK, -1:error)
        """
        res = self._stop_analog_output()

        error = 0
        try:
            # stop the counter task
            daq.DAQmxStopTask(self._scanner_counter_daq_task)
            # after stopping delete all the configuration of the counter
            daq.DAQmxClearTask(self._scanner_counter_daq_task)
            # set the task handle to None as a safety

            self._scanner_counter_daq_task = None
        except:
            self.log.exception('Could not close scanner counter.')
            error = -1

        return res | error

    def close_scanner_clock(self):
        """ Closes the clock and cleans up afterwards.

        @return int: error code (0:OK, -1:error)
        """
        try:
            # Stop the clock task:
            daq.DAQmxStopTask(self._scanner_clock_daq_task)

            # After stopping delete all the configuration of the clock:
            daq.DAQmxClearTask(self._scanner_clock_daq_task)

            # Set the task handle to None as a safety
            self._scanner_clock_daq_task = None

        except:
            self.log.exception('Could not close clock.')
            return -1

        return 0

    # ================ End ConfocalScannerInterface Commands ===================

    # ==================== ODMRCounterInterface Commands =======================

    def set_up_odmr_clock(self, clock_frequency=None, clock_channel=None,
                          idle=False):
        """ Configures the hardware clock of the NiDAQ card to give the timing.

        @param float clock_frequency: optional, if defined, this sets the
                                      frequency of the clock
        @param str clock_channel: optional, if defined, this is the physical
                                  channel of the clock
        @param bool idle: set whether idle situation of the counter (where
                          counter is doing nothing) is defined as
                            True  = 'Voltage High/Rising Edge'
                            False = 'Voltage Low/Falling Edge'

        @return int: error code (0:OK, -1:error)
        """

        # The clock for the scanner is created on the same principle as it is
        # for the counter. The same task variable _scanner_clock_daq_task is
        # used for the scanner counting.

        if self._odmr_clock_daq_task is not None:
            self.log.error('Another scanner counter clock is already running, '
                           'close this one first.')
            return -1

        # check whether only one clock pair is available, since in some NI cards
        # (e.g. M-series) only one clock channel pair can be used.
        if self._clock_daq_task is not None or self._scanner_clock_daq_task is not None:
            self.log.error('Only one clock channel is available!\n'
                           'Another scanner counter clock is already running, '
                           'close this one first in order to use it for your '
                           'purpose!')
            return -1

        # Create handle for task, this task will generate pulse signal for
        # photon counting
        self._odmr_clock_daq_task = daq.TaskHandle()

        # assign the clock frequency, if given
        if clock_frequency is not None:
            self._odmr_clock_frequency = float(clock_frequency)

        # assign the clock channel, if given
        if clock_channel is not None:
            curr_clock_ch = clock_channel
        else:
            curr_clock_ch = self._odmr_clock_channel

        # Adjust the idle state if necessary
        my_idle = daq.DAQmx_Val_High if idle else daq.DAQmx_Val_Low

        try:
            # Create the Task here:
            task_name = 'ODMRClock'
            daq.DAQmxCreateTask(task_name, daq.byref(self._odmr_clock_daq_task))

            daq.DAQmxCreateCOPulseChanFreq(
                # The task to which to add the channels
                self._odmr_clock_daq_task,
                # which channel is used?
                curr_clock_ch,
                # Name to assign to task (NIDAQ uses by # default the physical channel name as
                # the virtual channel name. If name is specified, then you must use the name
                # when you refer to that channel in other NIDAQ functions)
                'ODMR Clock Producer',
                # units, Hertz in our case
                daq.DAQmx_Val_Hz,
                # idle state
                my_idle,
                # initial delay
                0,
                # pulse frequency, divide by 2 such that length of semi period = count_interval
                self._odmr_clock_frequency / 2,
                # duty cycle of pulses, 0.5 such that high and low duration are both
                # equal to count_interval
                0.5)

            daq.DAQmxCfgImplicitTiming(
                # Define task
                self._odmr_clock_daq_task,
                # Sample Mode: set the task to generate a continuous amount of running samples
                daq.DAQmx_Val_ContSamps,
                # buffer length which stores temporarily the number of generated samples
                10000)

        except:
            self.log.exception('Error while setting up odmr clock.')
            return -1
        return 0

    def set_up_odmr(self, counter_channel=None, photon_source=None,
                    clock_channel=None, odmr_trigger_channel=None):
        """ Configures the actual counter with a given clock.

        @param string counter_channel: if defined, this is the physical channel
                                       of the counter
        @param string photon_source: if defined, this is the physical channel
                                     where the photons are to count from
        @param string clock_channel: if defined, this specifies the clock for
                                     the counter
        @param string odmr_trigger_channel: if defined, this specifies the
                                            trigger output for the microwave

        @return int: error code (0:OK, -1:error)
        """

        if self._odmr_clock_daq_task is None and clock_channel is None:
            self.log.error('No clock running, call set_up_clock before '
                           'starting the counter!')
            return -1

        if (self._odmr_counter_daq_task is not None or
                self._scanner_counter_daq_task is not None or
                self._counter_daq_task is not None):
            self.log.error('Another counter is already running, close this '
                           'one first.')
            return -1

        # in order to make it interface compatible, a list can be passed, but
        # for the M-series card only the first channel will be taken!
        if counter_channel is not None:
            curr_counter_ch = counter_channel
        else:
            curr_counter_ch = self._odmr_counter_channel

        if photon_source is not None:
            curr_photon_source = photon_source
        else:
            curr_photon_source = self._photon_source

        if clock_channel is not None:
            curr_clock_channel = clock_channel
        else:
            curr_clock_channel = self._odmr_clock_channel

        try:
            # This task will count photons with binning defined by the clock_channel
            self._odmr_counter_daq_task = daq.TaskHandle()  # Initialize a Task
            # Create task for the counter
            taskname = 'ODMRCounterTask'
            daq.DAQmxCreateTask(taskname, daq.byref(self._odmr_counter_daq_task))

            daq.DAQmxCreateCICountEdgesChan(
                self._odmr_counter_daq_task,
                # assign a counter channel
                curr_counter_ch,
                # nameToAssignToChannel
                'ODMR Counter In',
                # specify the edge
                daq.DAQmx_Val_Rising,
                # The value from which to start counting
                0,
                # Specifies whether to increment or decrement the counter on each edge.
                daq.DAQmx_Val_CountUp)


        except:
            self.log.exception('Error while setting up ODMR counting task.')
            return -1

        return 0

    def set_odmr_length(self, length=100):
        """ Sets up the trigger sequence for the ODMR and the triggered microwave.

        @param int length: length of microwave sweep in pixel

        @return int: error code (0:OK, -1:error)
        """
        if self._odmr_counter_daq_task is None:
            self.log.error('No ODMR counter is running, cannot scan a line '
                           'without one.')
            return -1

        self._odmr_length = length

        try:
            # Set up the necessary parts for the Counter In Task
            daq.DAQmxCfgSampClkTiming(
                # add to this task
                self._odmr_counter_daq_task,
                # use this channel as clock
                self._odmr_clock_channel + 'InternalOutput',
                # Maximum expected clock frequency
                self._odmr_clock_frequency,
                # Generate sample on falling edge
                daq.DAQmx_Val_Rising,
                # generate finite number of samples
                daq.DAQmx_Val_FiniteSamps,
                # number of samples to generate
                # The first pulse will start the count task, therefore +1.
                self._odmr_length + 1)

        except:
            self.log.exception('Error while setting up ODMR to scan a line.')
            return -1

        return 0

    def count_odmr(self, length=100):
        """ Sweeps the microwave and returns the counts on that sweep.

        @param int length: length of microwave sweep in pixel

        @return float[]: the photon counts per second
        """
        if self._odmr_counter_daq_task is None:
            self.log.error('No counter is running, cannot scan an ODMR line '
                           'without one.')
            return np.array([-1.])

        # check if length setup is correct, if not, adjust.
        self.set_odmr_length(length)

        try:
            # start the odmr counting task that acquires counts
            # synchronously
            daq.DAQmxStartTask(self._odmr_counter_daq_task)
        except:
            self.log.exception('Cannot start ODMR counter.')
            return np.array([-1.])

        try:
            daq.DAQmxStartTask(self._odmr_clock_daq_task)

            # wait for the scanner clock to finish
            daq.DAQmxWaitUntilTaskDone(
                # define task
                self._odmr_counter_daq_task,
                # maximal timeout for the counter times the positions
                self._RWTimeout * self._odmr_length)

            # count data will be written here
            self._odmr_data = np.full(
                (self._odmr_length + 1,),
                222,
                dtype=np.uint32)

            # number of samples which were read will be stored here
            n_read_samples = daq.int32()

            # actually read the counted photons
            daq.DAQmxReadCounterU32(
                # read from this task
                self._odmr_counter_daq_task,
                # Read number of double the# number of samples
                self._odmr_length + 1,
                # Maximal timeout for the read # process
                self._RWTimeout,
                # write into this array
                self._odmr_data,
                # length of array to write into
                self._odmr_length + 1,
                # number of samples which were actually read
                daq.byref(n_read_samples),
                # Reserved for future use. Pass NULL (here None) to this parameter.
                None)

            # stop the counter task
            daq.DAQmxStopTask(self._odmr_counter_daq_task)
            daq.DAQmxStopTask(self._odmr_clock_daq_task)

            # create a new array for the final data (this time of the length
            # number of samples)
            self._real_data = np.zeros((self._odmr_length,), dtype=np.uint32)

            # the counts are counted up and the current value is saved to the
            # current array index. To get the actual size of an entry the
            # previous value has to be subtracted.
            previous = self._odmr_data[0]
            for index, entry in enumerate(self._odmr_data[1:]):
                self._real_data[index] = entry - previous
                previous = entry

            # add upp adjoint pixels to also get the counts from the low time of
            # the clock:
            # self._real_data = self._odmr_data[:-1:2]
            # self._real_data += self._odmr_data[1:-1:2]

            return self._real_data * self._odmr_clock_frequency

        except:
            self.log.exception('Error while counting for ODMR.')
            return np.array([-1.])

    def close_odmr(self):
        """ Closes the odmr and cleans up afterwards.

        @return int: error code (0:OK, -1:error)
        """

        error = 0
        try:
            # stop the counter task
            daq.DAQmxStopTask(self._odmr_counter_daq_task)
            # after stopping delete all the configuration of the counter
            daq.DAQmxClearTask(self._odmr_counter_daq_task)
            # set the task handle to None as a safety

            self._odmr_counter_daq_task = None
        except:
            self.log.exception('Could not close odmr counter. Find out why!')
            error = -1

        return error

    def close_odmr_clock(self):
        """ Closes the odmr and cleans up afterwards.

        @return int: error code (0:OK, -1:error)
        """
        try:
            # Stop the clock task:
            daq.DAQmxStopTask(self._odmr_clock_daq_task)

            # After stopping delete all the configuration of the clock:
            daq.DAQmxClearTask(self._odmr_clock_daq_task)

            # Set the task handle to None as a safety
            self._odmr_clock_daq_task = None

        except:
            self.log.exception('Could not close odmr clock. Find out why!')
            return -1

        return 0

    # ================== End ODMRCounterInterface Commands ====================

    # Non Interface commands:

    # ======================== Digital channel control ==========================

    # NOT FINISHED AND NOT TESTED (alexander start):
    def digital_channel_switch(self, channel_name, mode=True):
        """
        Control the digital channels of the NI card.

        @param str channel_name: Name of the channel which should be controlled
                                 for example ('/Dev1/PFI9')
        @param bool mode: specifies if the voltage output of the chosen channel
                          should be turned on or off
                            mode=True   => On
                            mode=False  => Off

        @return int: error code (0:OK, -1:error)

        Switches on or off the voltage output (5V) of one of the digital
        channels, that can as an example be used to switch on or off the AOM
        driver or apply a single trigger for ODMR.
        """
        if channel_name == None:
            self.log.error('No channel for digital output specified')
            return -1
        else:

            self._digital_out_tasks = daq.TaskHandle()
            if mode:
                self._digital_data = daq.c_uint32(0xffffffff)
            else:
                self._digital_data = daq.c_uint32(0x0)

            self._digital_read = daq.c_int32()
            self._digital_samples_channel = daq.c_int32(1)
            daq.DAQmxCreateTask('DigitalOut', daq.byref(self._digital_out_task))

            daq.DAQmxCreateDOChan(self._digital_out_task,
                                  channel_name,
                                  "Digital Channel",
                                  daq.DAQmx_Val_ChanForAllLines)

            daq.DAQmxStartTask(self._digital_out_task)

            daq.DAQmxWriteDigitalU32(self._digital_out_task,
                                     self._digital_samples_channel,
                                     True,
                                     self._RWTimeout,
                                     daq.DAQmx_Val_GroupByChannel,
                                     np.array(self._digital_data),
                                     self._digital_read,
                                     None);

            daq.DAQmxStopTask(self._digital_out_task)
            daq.DAQmxClearTask(self._digital_out_task)

            return 0


import PyDAQmx as daq
from core.module import Base, StatusVar, ConfigOption


class NI6229CardAnalogControl(Base, AnalogControlInterface):
    """ Hardware control for Analog output of a voltage.

    unstable: Alexander Stark

    Tested for the Hardware card NI 6229.
    A analog control for voltages. Simplify the analog control just for one
    channels. If more are necessary, extend the code to multiple channels.

    config example:

        ni_6229_analog_cont:
            module.Class: 'ni_6229_card.NI6229CardAnalogControl'
            channel_ao: '/Dev2/AO3'
            voltage_range:
                - -10
                - 10
            RWTimeout: 10   # in seconds

    """

    _modtype = 'NI6229CardAnalogControl'
    _modclass = 'hardware'

    # config options
    _channel_ao = ConfigOption('channel_ao', missing='error')  # like '/Dev2/A03'
    _voltage_range = ConfigOption('voltage_range', missing='error')  # in V
    _RWTimeout = ConfigOption('RWTimeout', 10, missing='warn')  # in s.

    # Save current voltage to status variable
    _current_voltage = StatusVar('current_voltage', 0)

    def on_activate(self):
        """ Starts up the NI Card at activation. """

        # initialize all the task variables
        self._voltage_ao_task = None
        # self._current_voltage = 0   # in V.

        # Analog output is always needed and it does not interfere with the
        # rest, so start it always and leave it running
        if self._start_analog_output() < 0:
            self.log.error('Failed to start analog output.')
            raise Exception('Failed to start NI Card module due to analog output failure.')

    def on_deactivate(self):
        """ Shut down the NI card."""

        if self._stop_analog_output() < 0:
            self.log.error('Failed to stop analog output.')
            raise Exception('Failed to stop NI Card module due to analog output failure.')

    def _start_analog_output(self):
        """ Starts or restarts the analog output.

        @return int: error code (0:OK, -1:error)

        """
        try:
            # If an analog task is already running, kill that one first
            if self._voltage_ao_task is not None:
                # stop the analog output task
                daq.DAQmxStopTask(self._voltage_ao_task)

                # delete the configuration of the analog output
                daq.DAQmxClearTask(self._voltage_ao_task)

                # set the task handle to None as a safety
                self._voltage_ao_task = None

            # initialize ao channels / task for scanner, should always be active.
            # Define at first the type of the variable as a Task:
            self._voltage_ao_task = daq.TaskHandle()

            # create the actual analog output task on the hardware device. Via
            # byref you pass the pointer of the object to the TaskCreation function:
            daq.DAQmxCreateTask('SimpleAO', daq.byref(self._voltage_ao_task))
            # Assign and configure the created task to an analog output voltage channel.
            daq.DAQmxCreateAOVoltageChan(
                # The AO voltage operation function is assigned to this task.
                self._voltage_ao_task,
                # use (all) scanner ao_channels for the output
                self._channel_ao,
                # assign a name for that channel
                'AO Channel {0}'.format(3),
                # minimum possible voltage
                self._voltage_range[0],
                # maximum possible voltage
                self._voltage_range[1],
                # units is Volt
                daq.DAQmx_Val_Volts,
                # empty for future use
                '')
        except:
            self.log.exception('Error starting analog output task.')
            return -1
        return 0

    def _stop_analog_output(self):
        """ Stops the analog output.

        @return int: error code (0:OK, -1:error)
        """
        if self._voltage_ao_task is None:
            return -1
        retval = 0

        try:
            # stop the analog output task and clear it
            daq.DAQmxStopTask(self._voltage_ao_task)
            daq.DAQmxClearTask(self._voltage_ao_task)
            self._voltage_ao_task = None
        except:
            self.log.exception('Error stopping analog output.')
            retval = -1
        # try:
        #     daq.DAQmxSetSampTimingType(self._voltage_ao_task, daq.DAQmx_Val_OnDemand)
        # except:
        #     self.log.exception('Error changing analog output mode.')
        #     retval = -1
        return retval

    def get_voltage(self, channels=None):
        """ Retrieve the analog voltages.

        @param list channels: optional, if specific voltage values are
                              requested. The input should be in the form
                                    ['<channel_name1>','<channel_name2>',...]

        @return dict: the channels with the corresponding analog voltage. If
                      channels=None, all the available channels are returned.
                      The dict will have the form
                        {'<channel_name1>': voltage-float-value,
                         '<channel_name2>': voltage-float-value, ...}
        """

        volt_dict = {}

        if channels is not None:
            for channel_name in channels:
                if channel_name == self._channel_ao:
                    volt_dict[self._channel_ao] = self._current_voltage
                else:
                    self.log.eror('No analog channel with the name "{0}" is '
                                  'present or connected!'.format(channel_name))

            return volt_dict

        else:
            volt_dict[self._channel_ao] = self._current_voltage
            return volt_dict

    def set_voltage(self, volt_dict):
        """ Set the voltages.

        @param dict volt_dict: the input voltages in the form
                                    {'<channel_name1>': voltage-float-value,
                                     '<channel_name2>': voltage-float-value,
                                     ...}

        @return dict: All the actual voltage values, which were set to the
                      device. The return value has the same form as the input
                      dict.
        """

        for channel_name in volt_dict:

            voltage = volt_dict[channel_name]

            if channel_name == self._channel_ao:

                # simplify to one value output
                length = 1
                start = True

                if voltage < self._voltage_range[0]:
                    self.log.warning('Current voltage "{0}"V exceeds the '
                                     'voltage range [{1},{2}]! Set to lower '
                                     'voltage value "{3}"V.'
                                     ''.format(voltage,
                                               self._voltage_range[0],
                                               self._voltage_range[1],
                                               self._voltage_range[0]))
                    voltage = self._voltage_range[0]

                if voltage > self._voltage_range[1]:
                    self.log.warning('Current voltage "{0}"V exceeds the '
                                     'voltage range [{1},{2}]! Set to upper '
                                     'voltage value "{3}"V.'
                                     ''.format(voltage,
                                               self._voltage_range[0],
                                               self._voltage_range[1],
                                               self._voltage_range[1]))
                    voltage = self._voltage_range[1]

                v_list = np.array([voltage], dtype=np.float64)

                # Number of samples which were actually written, will be stored here.
                # The error code of this variable can be asked with .value to check
                # whether all channels have been written successfully.
                self._AONwritten = daq.int32()
                # write the voltage instructions for the analog output to the hardware
                daq.DAQmxWriteAnalogF64(
                    # write to this task
                    self._voltage_ao_task,
                    # length of the command (points)
                    length,
                    # start task immediately (True), or wait for software start (False)
                    start,
                    # maximal timeout in seconds for# the write process
                    self._RWTimeout,
                    # Specify how the samples are arranged: each pixel is grouped by channel number
                    daq.DAQmx_Val_GroupByChannel,
                    # the voltages to be written
                    v_list,
                    # The actual number of samples per channel successfully written to the buffer
                    daq.byref(self._AONwritten),
                    # Reserved for future use. Pass NULL(here None) to this parameter
                    None)

                self._current_voltage = voltage

            else:
                self.log.eror('No analog channel with the name "{0}" is '
                              'present or connected!'.format(channel_name))

        # do not check the actual set voltage, just pass further the input
        return volt_dict

    def get_channels(self):
        """ Ask for the available channels.

        @return list: all the available analog channel names in the form
                        ['<channel_name1>','<channel_name2>',...]
        """
        return [self._channel_ao]