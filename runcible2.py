#! /usr/bin/env python3
#RUNCIBLE - a raspberry pi / python sequencer for spanned 40h monomes inspired by Ansible Kria
#TODO:
#fix pattern copy - current pattern is wiped during copy? problem arises after introducing cue
#fix pattern cuing not quite in sync?
#fix too many files open - problem in spanner?
#adjust preset selection to allow for meta sequencing
#fix display of current preset
#add pattern cue timer
#add meta mode (pattern sequencing)
#
#add input/display for probability, as per kria - implement a next_note function which returns true or false based on probability setting for that track at that position
#
#test looping independent for each parameter - test this more thoroughly - disable for polyphonic tracks (where it doesn't make sense? - maybe it does?)
#test loop phase reset input as per kria
#
#add trigger entry on trigger screen if not parameters are not sync'd
#add note mutes for drum channel? - maybe note mutes are for the currently selected track
#at this stage, for polyphonic tracks, probabilities are per position - like velocity - not per note 
#
#enable a per channel transpose setting? 
#add scale editing 
#
#fix cutting - has to do with keys held
#enable looping around the end of the loop start_loop is higher than end_loop
#consider per row velocity settings for polyphonic tracks
#
#tweak note duration - get the right scaled values 
#adjust use of duration settings 1/8, 1/16 & 1/32 notes?  (6 duration positions = 1/32, 1/16, 1/8, 1/4, 1/2, 1)
#
#make note entry screen monophonic? - clear off other notes in that column if new note is entered - this should be configurable maybe on trigger page?
#
#add settings screen with other adjustments like midi channel for each track?
#fix pauses - network? other processes?
#fix clear all on disconnect

import copy
import pickle
import os
import sys
import subprocess
import asyncio
import monome
import virtualgrid
import clocks
import rtmidi2
from enum import Enum

# see Channel Mode Messages for Controller Numbers
CONTROLLER_CHANGE = CONTROL_CHANGE = 0xB0
# 1011cccc 0ccccccc 0vvvvvvv (channel, controller, value)

PROGRAM_CHANGE = 0xC0
# 1100cccc 0ppppppp (channel, program)
# controller value byte should be 0

ALL_SOUND_OFF = 0x78
# controller value byte should be 0
RESET_ALL_CONTROLLERS = 0x79
# 0 = off, 127 = on
LOCAL_CONTROL = LOCAL_CONTROL_ONOFF = 0x7A
# controller value byte should be 0
ALL_NOTES_OFF = 0x7B
# controller value byte should be 0, also causes ANO

def cancel_task(task):
    if task:
        task.cancel()

class Modes(Enum):
    mTr = 0
    mNote = 1
    mOct = 2
    mDur = 3
    mVel = 4
    mScale = 5
    mPattern = 6

class ModModes(Enum):
    modNone = 1
    modLoop = 2
    modTime = 3
    modProb = 4

class Note:
    def __init__(self,channel_inc = 0, pitch = 0, velocity = 0, duration=0):
        self.channel_inc = channel_inc #this is the increment to the global base channel
        self.pitch = pitch
        self.velocity = velocity
        self.duration = duration

    def decrement_duration(self):
        if self.duration > 0: 
            self.duration = self.duration - 1

class Track:
    def __init__(self,track_id):
        self.num_params = 4
        self.tr = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]
        self.octave = [0 for i in range(16)]
        self.note = [list() for i in range(16)]
        self.duration = [1 for i in range(16)]
        self.velocity = [3 for i in range(16)]
        self.params = [[0] * self.num_params for i in range (16)] #initialise a 4x16 array
        self.dur_mul = 1; #duration multiplier
        self.lstart = [0,0,0,0,0]
        self.lend = [15,15,15,15,15]
        self.last_pos = [15,15,15,15,15]
        self.next_pos = [15,15,15,15,15]
        self.swap = [[0] * self.num_params] # what is this actually for?
        self.tmul = [1,1,1,1,1]
        self.pos = [0,0,0,0,0] #current position for each parameter in each track - replaces play_position
        self.pos_mul = [0,0,0,0,0]  #something to do with the time multiplier
        self.pos_reset = False
        self.track_id = track_id
        self.play_position = 0 # will switch to position for each parameter
        self.next_position = 0 # will switch to position for each parameter
        self.loop_start = 0  # will eventually switch to loop start / end per parameter but keep it simple for now
        self.loop_end = 15
        self.loop_count = 0
        self.loop_first = 0
        self.loop_last = 0
        self.loop_edit = 0
        self.scale_toggle = 1
        self.track_mute = 0
        self.sync_mode = 1


class Pattern:
    def __init__(self,pattern_id):
        self.pattern_id = pattern_id
        self.tracks = [Track(i) for i in range(4)]
        self.step_ch1 = [[0 for col in range(16)] for row in range(8)] #used for display of notes
        self.step_ch2 = [[0 for col in range(16)] for row in range(8)]
        self.step_ch3 = [[0 for col in range(16)] for row in range(8)]
        self.step_ch4 = [[0 for col in range(16)] for row in range(8)]


class Preset:
    def __init__(self):
        self.patterns = [Pattern(i) for i in range(16)]
        self.current_pattern = 0
        self.meta_pat = [[0] * 64]
        self.meta_steps = [[0] * 64]
        self.meta_start = 0
        self.meta_end = 0
        self.meta_len = 0
        self.meta_lswap = 0
        self.glyph = [[0] * 8]
        # this needs to be in the Preset into state so custom scales are stored
        self.scale_data = [[48,2,2,1,2,2,2,1],
                           [48,2,1,2,2,1,2,2],
                           [48,2,2,1,2,2,2,1],
                           [48,2,1,2,2,2,1,2],
                           [48,1,2,2,2,1,2,2],
                           [48,2,2,2,1,2,2,1],
                           [48,2,2,1,2,2,1,2],
                           [48,2,1,2,2,1,2,2],
                           [48,1,2,2,1,2,2,2],
                           [48,3,2,2,3,2,3,2],
                           [48,2,2,3,2,3,2,2],
                           [48,3,2,1,1,3,2,3],
                           [48,1,3,1,2,1,2,2],
                           [48,0,0,0,0,0,0,0],
                           [48,0,0,0,0,0,0,0],
                           [48,0,0,0,0,0,0,0],
                           [48,0,0,0,0,0,0,0],
                           [48,0,0,0,0,0,0,0]]

class State:
    def __init__(self):
        self.clock_period = 0
        self.current_preset_id = 0
        self.note_sync = True
        self.loop_sync = 0
        self.cue_div = 4
        self.cue_steps = 4
        self.meta = 0
        self.presets = [Preset() for i in range(15)]

#runcible sequencer, based on ansible kria
class Runcible(monome.App):
    def __init__(self, clock, ticks, midi_out,channel_out,clock_out,other):
        super().__init__()
        self.prefix = "runcible"
        self.clock = clock
        self.ticks = ticks
        self.midi_out = midi_out
        self.channel = channel_out
        self.clock_ch = clock_out
        self.cur_scale = [0,0,0,0,0,0,0,0]
        self.cur_scale_id = 0
        self.cur_trans = 0
        self.k_mode = Modes.mNote
        self.k_mod_mode = ModModes.modNone
        self.state = State()
        #self.note_on = [[Note()] for i in range(96)] #full resolution
        self.note_on = [[Note()] for i in range(16)]
        #self.note_off = [[Note()] for i in range(96)]
        self.note_off = [[Note()] for i in range(16)]
        self.duration_timers = [Note()] 
        #call ready() directly because virtual device doesn't get triggered
        self.pickle_file_path = "/home/pi/monome/runcible/runcible.pickle" 
        self.ctrl_keys_held = 0
        self.ctrl_keys_last = list()
        #self.ready()

    def on_grid_ready(self):
        self.current_pos = 0
        self.cue_sub_pos = 0
        self.cue_pos = 0
        self.cue_pat_next = 0
        #self.play_position = [0,0,0,0] # one position for each track
        #self.fine_play_position = 0
        #self.next_position = [0,0,0,0]
        self.cutting = False
        #remove loop from main logic
        #self.loop_start = [0,0,0,0]
        #self.loop_end = [self.width - 1, self.width -1, self.width -1, self.width -1]
        #self.loop_length = [self.width, self.width, self.width, self.width]
        self.keys_held = 0
        self.key_last = list() 

        self.current_pitch = 0
        self.current_oct = 0
        self.current_dur = 1
        self.current_vel = 3

        if os.path.isfile(self.pickle_file_path):
            self.restore_state()
        self.current_preset = self.state.presets[0]
        self.current_pattern = self.current_preset.patterns[self.current_preset.current_pattern]
        self.current_track = self.current_pattern.tracks[0]
        self.current_track_id = self.current_pattern.tracks[0].track_id
        #self.calc_scale(self.cur_scale_id)
        self.frame_dirty = False 
        asyncio.async(self.play())

    @asyncio.coroutine
    def play(self):
        print("playing")
        self.current_pos = yield from self.clock.sync()
        while True:
            yield from self.clock.sync(self.ticks//2)
            self.current_pos = yield from self.clock.sync()
            #print(self.current_pos%16)
            led_pos = self.current_pos%16
            self.grid.led_set(led_pos,0,1)
            self.grid.led_set((led_pos-1)%16,0,0)
            self.grid.led_set((led_pos-2)%16,0,0)
            #self.grid.led_set((led_pos-3)%16,0,0)

    def dummy_disconnect(self):
        print("Disconnecting... thanks for playing!")

    def disconnect(self):
        print("Disconnecting... thanks for playing!")
        for channel in range(16):
            self.midi_out.send_cc(channel,ALL_SOUND_OFF, 0)
            self.midi_out.send_cc(channel, RESET_ALL_CONTROLLERS, 0)
        self.midi_out.close_port()
        self.save_state()
        super().disconnect()
        sys.exit(0)
        #command = "/usr/bin/sudo /sbin/shutdown -h now"
        #process = subprocess.Popen(command.split(), stdout=subprocess.PIPE)
        #output = process.communicate()[0]
        #print(output)

    def restore_state(self):
        #load the pickled AST for this feature
        self.state = pickle.load(open(self.pickle_file_path, "rb"))

    def save_state(self):
        with open(self.pickle_file_path, 'wb') as pickle_handle:
            pickle.dump(self.state, pickle_handle)


if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    clock_out = 3
    print("Available ports:",rtmidi2.get_out_ports())
    midiport = rtmidi2.MidiOut().ports_matching("iConnectMIDI4+ 20:5")
    midi_out = rtmidi2.MidiOut()
    if midiport:
        midi_out.open_port(midiport[0])
        print ("using output_id : %s " % midi_out.get_port_name(midiport[0]))
    else:
        print ("Port not found")
    print ("using clock source: %s " % clock_out)
    channel_out = 2
    #midi_out=None

    # create internal clock
    #coro = loop.create_datagram_endpoint(clocks.FooClock, local_addr=('127.0.0.1', 9000))
    #transport, clock = loop.run_until_complete(coro)
    #clock = clocks.InaccurateTempoClock(120)

    clock = clocks.RtMidiClock()
    runcible_app  = Runcible(clock,6,midi_out,channel_out,clock_out,None)

    try: 
        asyncio.async(virtualgrid.SpanningSerialOsc.create(loop=loop, autoconnect_app=runcible_app))
        loop.run_forever()
    except KeyboardInterrupt:
        runcible_app.disconnect()
        midi_out.close_port()
        print('kthxbye')

