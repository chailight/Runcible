#! /usr/bin/env python3
#RUNCIBLE - a raspberry pi / python sequencer for spanned 40h monomes inspired by Ansible Kria
#TODO:
#fix cutting crash
#fix cueing so it stays in sync
#fix loop input on trigger page
#fix pattern dispaly - display meta pattern details
#fix polyphonic mode - monophonic notes are bleeding between tracks - use polyphonic fix?? 
#add polyphonic mutes

#fix pattern copy - current pattern is wiped during copy? problem arises after introducing cue
#fix pattern cuing not quite in sync?
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
import numpy as np
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

TICKS_32ND = 96 // 32         # 3
TICKS_SEXTUPLET = 96 // 24    # 4
TICKS_16TH = 96 // 16         # 6
TICKS_TRIPLET = 96 // 12      # 8
TICKS_8TH = 96 // 8           # 12 
TICKS_QUARTER = 96 // 4       # 24
TICKS_HALF = 96 // 2          # 48
TICKS_WHOLE = 96 // 1         # 96

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
        self.num_params = 6
        self.tr = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]
        self.octave = [0 for i in range(16)]
        self.note = [list() for i in range(16)]
        self.alt_note = [list() for i in range(16)]
        self.duration = [1 for i in range(16)]
        self.velocity = [3 for i in range(16)]
        #self.params = [[0] * self.num_params for i in range (16)] #initialise a 4x16 array
        self.prob  = [[4] * self.num_params for i in range (16)] #initialise probability for each parameter
        self.dur_mul = 1; #duration multiplier
        self.lstart = [0,0,0,0,0]
        self.lend = [15,15,15,15,15]
        self.last_pos = [15,15,15,15,15]
        self.next_pos = [15,15,15,15,15]
        self.swap = [[0] * self.num_params] # what is this actually for?
        self.tmul = [5,5,5,5,5]
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
        self.polyphonic = 0


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
        self.cue_div = 5 #defalut to 16th, i.e. 6-1
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
        #self.k_mode = Modes.mTr
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
        #self.loop_end = [self.grid.width - 1, self.grid.width -1, self.grid.width -1, self.grid.width -1]
        #self.loop_length = [self.grid.width, self.grid.width, self.grid.width, self.grid.width]
        self.keys_held = 0
        self.key_last = list()

        self.current_pitch = [[0,0,0,0,0,0] for i in range(4)] # allow upto 6 note polyphony for each track
        self.current_oct = 0
        self.current_dur = 1
        self.current_vel = 3

        if os.path.isfile(self.pickle_file_path):
            self.restore_state()
        self.current_preset = self.state.presets[0]
        self.current_pattern = self.current_preset.patterns[self.current_preset.current_pattern]
        self.current_track = self.current_pattern.tracks[0]
        self.current_track_id = self.current_pattern.tracks[0].track_id
        self.calc_scale(self.cur_scale_id)
        self.my_buffer = virtualgrid.myGridBuffer(self.grid.width, self.grid.height)
        self.my_pos_buffer = np.array([[1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]])
        self.track_buffer = np.array([[1,0,0,0,0]])
        self.mode_buffer = np.array([[1,0,0,0,0,0,0,0,0,0,0]])
        #self.buffer.levels.reverse() #flip the buffer - for some reason it is upsidedown compared to the grid
        self.frame_dirty = False
        asyncio.async(self.play())

    def next_step(self, track, parameter):
       #print("track.pos_mul: ", parameter, track.pos_mul[parameter])
       #print("track.tmul: ", parameter, self.current_pattern.tracks[track.track_id].tmul[parameter])
       track.pos_mul[parameter] = int(track.pos_mul[parameter]) + 1

       if track.pos_mul[parameter] >= self.current_pattern.tracks[track.track_id].tmul[parameter]:
            if track.pos[parameter] == self.current_pattern.tracks[track.track_id].lend[parameter]:
                track.pos[parameter] = self.current_pattern.tracks[track.track_id].lstart[parameter]
            else:
                track.pos[parameter] = int(track.pos[parameter]) + 1
                if track.pos[parameter] > 15:
                    track.pos[parameter] = 0
            track.pos_mul[parameter] = 0
            # add probabilities
            return True
       else:
            return False

    def next_step_new(self, track, parameter):
       print("track.pos_mul: ", parameter, track.pos_mul[parameter])
       print("track.tmul: ", parameter, self.current_pattern.tracks[track.track_id].tmul[parameter])
       #track.pos_mul[parameter] = int(track.pos_mul[parameter]) + 1

       #advance the parameter position if the current position falls on an even division of the time multiplier
       if (self.current_pos % self.current_pattern.tracks[track.track_id].tmul[parameter]) == 0:
            if track.pos[parameter] == self.current_pattern.tracks[track.track_id].lend[parameter]:
                track.pos[parameter] = self.current_pattern.tracks[track.track_id].lstart[parameter]
            else:
                track.pos[parameter] = int(track.pos[parameter]) + 1
                if track.pos[parameter] > 15:
                    track.pos[parameter] = 0
            track.pos_mul[parameter] = 0
            # add probabilities
            return True
       else:
            return False

    @asyncio.coroutine
    def play(self):
        print("playing")
        #self.current_pos = yield from self.clock.sync(TICKS_32ND)
        #self.current_pos = yield from self.clock.sync(self.ticks)
        self.current_pos = yield from self.clock.sync()

        self.cue_sub_pos = self.cue_sub_pos + 1
        if self.cue_sub_pos >= self.state.cue_div + 1:
            self.cue_sub_pos = 0
            self.cue_pos = self.cue_pos + 1
            if self.cue_pos >= self.state.cue_steps + 1:
                self.cue_pos = 0

        for t in self.current_pattern.tracks:
            #self.loop_length[t] = abs(self.loop_end[self.current_track] - self.loop_start[t])+1
            t.loop_length = abs(t.loop_end - t.loop_start)+1
            t.play_position = (self.current_pos//self.ticks)%t.loop_length + t.loop_start
            #t.tmul=[TICKS_16TH,TICKS_16TH,TICKS_16TH,TICKS_16TH,TICKS_16TH] ### remove this after testing is done

        while True:
            self.frame_dirty = True #if nothing else has happend, at least the position has moved
            #print("calling draw at position: ", self.current_pos)
            self.draw()
            #insert triggering logic here
            for track in self.current_pattern.tracks:
                if track.pos_reset:
                    for p in range(5):
                        track.pos[p] = track.lend[p] 
                    track.pos_reset = False

                if self.next_step(track, Modes.mNote.value):
                    #if len(track.note[track.pos[Modes.mNote.value]]) > 0: #need to allow for situations where there is no notes yet
                        #self.current_pitch = [0,0,0,0,0,0] # clear any residual values, assuming monophonic
                    #    self.current_pitch[0] = track.note[track.pos[Modes.mNote.value]][0] #need to adjust for polyphonic
                    #self.current_pitch = [0,0,0,0,0,0] # clear any residual values
                    #print("track_note: ", track.note[track.pos[Modes.mNote.value]])
                    #print("track_trig: ", track.note[track.pos[Modes.mTr.value]])
                    #if track.note[track.pos[Modes.mNote.value]]:
                    if track.polyphonic:
                        for i in range(len(track.note[track.pos[Modes.mNote.value]])): #this needs to be fixed so that polyphonic mode forces track sync
                            #print("poly current_pitch: ", track.pos[Modes.mNote.value], i, self.current_pitch[i])
                            self.current_pitch[track.track_id][i] = track.note[track.pos[Modes.mNote.value]][i] #need to adjust for polyphonic
                    elif len(track.note[track.pos[Modes.mNote.value]]) > 0: #need to allow for situations where there is no notes yet
                        self.current_pitch[track.track_id][0] = track.note[track.pos[Modes.mNote.value]][0] #need to adjust for polyphonic
                    #else:
                    #    self.current_pitch[0] = track.note[track.pos[Modes.mNote.value]][0] #need to adjust for polyphonic
                        #print("mono current_pitch: ", track.pos[Modes.mNote.value], self.current_pitch[0])
                    #else:
                    #    self.current_pitch[0] = 0 # default???
                        #print("default current_pitch: ", track.pos[Modes.mNote.value], self.current_pitch[0])

                if self.next_step(track, Modes.mOct.value):
                    self.current_oct = track.octave[track.pos[Modes.mOct.value]]

                if self.next_step(track, Modes.mDur.value):
                    self.current_dur = track.duration[track.pos[Modes.mDur.value]]
                    #print("current_dur: ", self.current_dur)

                if self.next_step(track, Modes.mVel.value):
                    self.current_vel = track.velocity[track.pos[Modes.mVel.value]]
                    #print("current_vel: ", self.current_vel)

                if self.next_step(track, Modes.mTr.value):
                    #if track.tr[track.play_position] == 1:
                    if track.tr[track.pos[Modes.mTr.value]] == 1:
                        scaled_duration = 0
                        #entered_duration = track.duration[track.play_position]
                        entered_duration = self.current_dur
                        if entered_duration == 1:
                            scaled_duration = TICKS_32ND
                        if entered_duration == 2:
                            scaled_duration = TICKS_16TH
                        if entered_duration == 3:
                            scaled_duration =  TICKS_8TH
                        if entered_duration == 4:
                            scaled_duration = TICKS_QUARTER
                        elif entered_duration == 5:
                            scaled_duration = TICKS_HALF
                        elif entered_duration == 6:
                            scaled_duration = TICKS_WHOLE
                        #velocity = track.velocity[track.play_position]*20
                        #velocity = track.velocity[track.pos[Modes.mTr.value]]*20
                        velocity = self.current_vel*20
                        #print("velocity: ", velocity)
                        #velocity = 65
                        #print("entered: ", entered_duration, "scaled duration: ", scaled_duration)
                        polyphony = 1 #assume monophonic and therefore iterate one time only
                        if track.polyphonic:
                            polyphony = len(track.note[track.pos[Modes.mNote.value]]) #set polyphony to number of notes at this position if track is polyphonic
                        for i in range(polyphony): #this needs to be fixed so that polyphonic mode forces track sync
                            #print("track: ", track.track_id, "note# ", i+1, "of", polyphony, "current_pitch", self.current_pitch)
                            # add toggles here for loop sync - if track then set position to mTr.value, else set to parameter 
                            #self.current_pitch[i] = track.note[track.pos[Modes.mNote.value]][i] #need to adjust for polyphonic
                            if track.scale_toggle:
                                current_note = abs(self.cur_scale[self.current_pitch[track.track_id][i]-1] + self.current_oct*12) #may have to introduce a check for self.current_pitch not being zero
                            #    print("input note: ", self.current_pitch, "current note: ", current_note)
                            else:
                                #set the note to an increment from some convenient base
                                current_note = abs(self.current_pitch[track.track_id][i]+35 + self.current_oct*12)
                            #    print("input note: ", self.current_pitch, "current note: ", current_note)

                            if not track.track_mute:
                                #self.insert_note(track.track_id, track.play_position, current_note, velocity, scaled_duration) # hard coding velocity
                                self.insert_note(track.track_id, track.pos[Modes.mTr.value], current_note, velocity, scaled_duration) # hard coding velocity
                            #    print("calling insert note: ",current_note, velocity,scaled_duration, "on track: ", track.track_id, "at pos: ", track.pos[Modes.mTr.value])

            #asyncio.async(self.trigger())
            self.trigger()
            self.current_pos = yield from self.clock.sync(self.ticks)

            self.cue_sub_pos = self.cue_sub_pos + 1
            if self.cue_sub_pos > self.state.cue_div:
                self.cue_sub_pos = 0
                self.cue_pos = self.cue_pos + 1
                if self.cue_pos > self.state.cue_steps:
                    self.cue_pos = 0
                    if self.cue_pat_next:
                        #self.change_pattern(self.cue_pat_next -1)
                        self.current_preset.current_pattern = self.cue_pat_next - 1
                        self.current_pattern = self.current_preset.patterns[self.current_preset.current_pattern]
                        self.current_track = self.current_pattern.tracks[self.current_track_id]
                        self.cue_pat_next = 0

            for track in self.current_pattern.tracks:
                track.loop_length = abs(track.loop_end - track.loop_start)+1
                track.play_position = (self.current_pos//self.ticks)%track.loop_length + track.loop_start

    def insert_note(self,track,position,pitch,velocity,duration):
        self.set_note_on(track,position,pitch,velocity,duration)
        #asyncio.async(self.set_note_on(track,position,pitch,velocity,duration))
        #self.insert_note_off(track,(position+duration)%16,pitch)
        #print("setting note on at: ", position, " + ", self.current_pattern.tracks[track].duration[position])
        #print("setting note off at: ", position, " + ", self.current_pattern.tracks[track].duration[position])
        #asyncio.async(self.set_note_off_timer(track,duration,pitch))

    ####### deprecated !!!
    #def insert_note_on(self,track,position,pitch,velocity):
        #already_exists = False
        #for n in self.note_on[position]:
            #if n.pitch == pitch:
                #already_exists = True
                ##print("note on exists", self.channel + track, pitch, "at position: ", position)
        #if not already_exists:
            #new_note = Note(track,pitch,velocity)
            #self.note_on[position].append(new_note)
            ##pos = yield from self.clock.sync()
            ##print("setting note on ", self.channel + track, pitch, "at pos: ", position)

    ####### deprecated !!!
    #def insert_note_off(self,track,position,pitch):
        #already_exists = False
        #for n in self.note_off[position]:
            #if n.pitch == pitch:
                #already_exists = True
                ##print("note off exists", self.channel + track, pitch, "at position: ", position)
        #if not already_exists:
            #new_note = Note(track,pitch,0)
            #self.note_off[position].append(new_note)
            ##pos = yield from self.clock.sync()
            #print("setting note off ", self.channel + track, pitch, "at pos: ", position)

    #@asyncio.coroutine
    def set_note_on(self,track,position,pitch,velocity,duration):
        already_exists = False
        for n in self.note_on[position]:
            if n.pitch == pitch:
                already_exists = True
                print("warning! duplicate note. pitch:", pitch,  " ch: ", self.channel + track, "at position: ", position)
        if not already_exists:
            new_note = Note(track,pitch,velocity,duration)
            self.note_on[position].append(new_note)
            #pos = yield from self.clock.sync()
            #self.midi_out.send_noteon(self.channel + track, pitch, velocity)
            self.duration_timers.append(new_note) # add this to the list of notes to track for when they end
            #print("set note on: ", self.channel + track, pitch, "at: ", position)

    #@asyncio.coroutine
    #def set_note_off_timer(self,track,duration,pitch):
    #    pos = yield from self.clock.sync(duration*4)
    #    #self.midi_out.send_noteon(self.channel + track, pitch,0)
    #    #print("note off timer", self.channel + track, pitch, "at: ", pos%16)

    def calc_scale(self, s):
        self.cur_scale[0] = self.current_preset.scale_data[s][0] + self.cur_trans
        for i1 in range(1,8):
            self.cur_scale[i1] = self.cur_scale[i1-1] + self.current_preset.scale_data[s][i1]


    #@asyncio.coroutine
    #async def trigger(self):
    def trigger(self):
        #print("trigger called")
        # play all notes in this position
        for t in self.current_pattern.tracks:
            #for note in self.note_off[t.play_position]:
            #for note in self.note_off[t.pos[Modes.mTr.value]]:
            #del self.note_off[t.play_position][:] #clear the current midi output once it's been sent
            #del self.note_off[t.pos[Modes.mTr.value]][:] #clear the current midi output once it's been sent

            #for note in self.note_on[t.play_position]:
            for note in self.note_on[t.pos[Modes.mTr.value]]:
                self.midi_out.send_noteon(self.channel + note.channel_inc, note.pitch,note.velocity)
                #print("playing note", self.channel + note.channel_inc, note.pitch, " at: ",self.current_pos%32)
            del self.note_on[t.pos[Modes.mTr.value]][:] #clear the current midi output once it's been sent

        #end all notes that have expired
        i = 0
        finished_notes = list()
        new_duration_timers = [Note()]
        for note in self.duration_timers:
            note.decrement_duration()
            #print("decreasing duration for note:", note.pitch, "at: ", self.current_pos%32, "to: ", note.duration )
            if note.duration == 0:
                self.midi_out.send_noteon(self.channel + note.channel_inc, note.pitch,0)
                #print("ending note", self.channel + note.channel_inc, note.pitch, " at: ", self.current_pos%32)
                finished_notes.append(i) # mark this note for removal from the timer list
            else:
                new_duration_timers.append(note)
            i = i + 1
        del self.duration_timers[:]
        self.duration_timers = new_duration_timers # set the duration timers list to the be non-zero items
        #for n in finished_notes:
        #    del self.duration_timers[n] #clear the timer once it's exhausted 


    #@asyncio.coroutine
    #def clock_out(self):
    #    yield from self.clock.sync(self.ticks)

    #def draw_current_position_test(self):
    #    previous_step = [0,0,0,0]
    #    if self.my_buffer.levels[0+self.current_track.track_id][self.current_track.pos[self.k_mode.value]] == 0:
    #        self.my_buffer.led_set(self.current_track.pos[self.k_mode.value]-1, 7, previous_step[self.current_track.track_id])
    #        self.my_buffer.led_set(self.current_track.pos[self.k_mode.value], 7, 15)
    #        previous_step[self.current_track.track_id] = 0
    #    else: #toggle an already lit led as we pass over it
    #        previous_step[self.current_track.track_id] = 15
    #        self.my_buffer.led_set(self.current_track.pos[self.k_mode.value], 7, 0)

    def get_tmul_display(self, multiplier):
        tmul_value = 0
        if multiplier == TICKS_32ND - 1:
            tmul_value = 0
        elif multiplier == TICKS_SEXTUPLET - 1:
            tmul_value = 1
        elif multiplier == TICKS_16TH - 1:
            tmul_value = 2
        elif multiplier == TICKS_TRIPLET - 1:
            tmul_value = 3
        elif multiplier == TICKS_8TH - 1:
            tmul_value =4
        elif multiplier == TICKS_QUARTER - 1:
            tmul_value = 5
        elif multiplier == TICKS_HALF - 1:
            tmul_value = 5
        elif multiplier == TICKS_WHOLE - 1:
            tmul_value = 6
        elif multiplier == (TICKS_WHOLE * 2) - 1:
            tmul_value = 7
        elif multiplier == (TICKS_WHOLE * 3) - 1:
            tmul_value = 8
        elif multiplier == (TICKS_WHOLE * 4) - 1:
            tmul_value = 9
        elif multiplier == (TICKS_WHOLE * 5) - 1:
            tmul_value = 10
        elif multiplier == (TICKS_WHOLE * 6) - 1:
            tmul_value = 11
        elif multiplier == (TICKS_WHOLE * 7) - 1:
            tmul_value = 12
        elif multiplier == (TICKS_WHOLE * 8) - 1:
            tmul_value = 13
        elif multiplier == (TICKS_WHOLE * 9) - 1:
            tmul_value = 14
        elif multiplier == (TICKS_WHOLE * 10) - 1:
            tmul_value = 15
        return tmul_value

    def draw_current_position(self):
            if self.k_mode == Modes.mTr:
                if self.k_mod_mode == ModModes.modTime:
                    for track in self.current_pattern.tracks:
                        # light up the current time multiplier
                        self.my_buffer.led_row(0,7-track.track_id,np.roll((self.my_pos_buffer).astype(int),self.get_tmul_display(track.tmul[self.k_mode.value]),axis=1))
                elif self.k_mod_mode == ModModes.modLoop:
                    for track in self.current_pattern.tracks:
                        #print("loop start/end",track.lstart[Modes.mTr.value],track.lend[Modes.mTr.value])
                        #loop_display_start = np.zeros(track.lstart[Modes.mTr.value],int).tolist()
                        #loop_display_middle = np.ones(track.lend[Modes.mTr.value]+1,int).tolist()
                        #loop_display_end = np.ones(15-track.lend[Modes.mTr.value],int).tolist()
                        #print(loop_display_start,loop_display_middle,loop_display_end)
                        #print(np.asarray(np.block([np.zeros(track.lstart),np.ones(track.lend+1),np.zeros(15-track.lend)])))
                        self.my_buffer.led_row(0,7-track.track_id,np.block([np.zeros(track.lstart[Modes.mTr.value],int),np.ones(track.lend[Modes.mTr.value]+1-track.lstart[self.k_mode.value],int),np.zeros(15-track.lend[Modes.mTr.value],int)]).tolist())
                        #for i in range(16):
                        #    if i >= track.lstart[Modes.mTr.value] and i <= track.lend[Modes.mTr.value]:
                        #        self.my_buffer.led_set(i,7-track.track_id,15)
                        #    else:
                        #        self.my_buffer.led_set(i,7-track.track_id,0)
                else:
                    self.my_buffer.led_row(0,7,np.array([self.current_pattern.tracks[0].tr])-np.roll((self.my_pos_buffer).astype(int),self.current_pattern.tracks[0].pos[self.k_mode.value]-1,axis=1))
                    self.my_buffer.led_row(0,7,np.array([self.current_pattern.tracks[0].tr])+np.roll((self.my_pos_buffer).astype(int),self.current_pattern.tracks[0].pos[self.k_mode.value],axis=1))
                    self.my_buffer.led_row(0,6,np.array([self.current_pattern.tracks[1].tr])-np.roll((self.my_pos_buffer).astype(int),self.current_pattern.tracks[1].pos[self.k_mode.value]-1,axis=1))
                    self.my_buffer.led_row(0,6,np.array([self.current_pattern.tracks[1].tr])+np.roll((self.my_pos_buffer).astype(int),self.current_pattern.tracks[1].pos[self.k_mode.value],axis=1))
                    self.my_buffer.led_row(0,5,np.array([self.current_pattern.tracks[2].tr])-np.roll((self.my_pos_buffer).astype(int),self.current_pattern.tracks[2].pos[self.k_mode.value]-1,axis=1))
                    self.my_buffer.led_row(0,5,np.array([self.current_pattern.tracks[2].tr])+np.roll((self.my_pos_buffer).astype(int),self.current_pattern.tracks[2].pos[self.k_mode.value],axis=1))
                    self.my_buffer.led_row(0,4,np.array([self.current_pattern.tracks[3].tr])-np.roll((self.my_pos_buffer).astype(int),self.current_pattern.tracks[3].pos[self.k_mode.value]-1,axis=1))
                    self.my_buffer.led_row(0,4,np.array([self.current_pattern.tracks[3].tr])+np.roll((self.my_pos_buffer).astype(int),self.current_pattern.tracks[3].pos[self.k_mode.value],axis=1))
                    #track_2_pos = np.roll((self.my_pos_buffer).astype(int),self.current_pattern.tracks[1].pos[self.k_mode.value],axis=1)
                    #track_3_pos = np.roll((self.my_pos_buffer).astype(int),self.current_pattern.tracks[2].pos[self.k_mode.value],axis=1)
                    #track_4_pos = np.roll((self.my_pos_buffer).astype(int),self.current_pattern.tracks[3].pos[self.k_mode.value],axis=1)

                    #track_1_pos = np.roll((self.my_pos_buffer).astype(int),self.current_pattern.tracks[0].pos[self.k_mode.value],axis=1)
                    #track_2_pos = np.roll((self.my_pos_buffer).astype(int),self.current_pattern.tracks[1].pos[self.k_mode.value],axis=1)
                    #track_3_pos = np.roll((self.my_pos_buffer).astype(int),self.current_pattern.tracks[2].pos[self.k_mode.value],axis=1)
                    #track_4_pos = np.roll((self.my_pos_buffer).astype(int),self.current_pattern.tracks[3].pos[self.k_mode.value],axis=1)
                    #remaining_screen = np.split(self.my_buffer.levels,[4],axis=1)[0]
                    #self.my_buffer.led_map(0,0,(np.block([remaining_screen,track_4_pos.T,track_3_pos.T,track_2_pos.T,track_1_pos.T])))
                    #self.my_buffer.led_map(0,0,(np.concatenate((np.asarray(np.split(self.my_buffer.levels,[5],axis=1)[0]),np.roll((self.my_pos_buffer).astype(int),self.current_track.pos[self.k_mode.value],axis=1).T,),axis=1)))
                    #previous_step = [0,0,0,0]
                    #track 1
                    #if track.pos[Modes.mTr.value] >= track.lstart[Modes.mTr.value] and track.pos[Modes.mTr.value] <= track.lend[Modes.mTr.value]:
                    #if ((self.current_pos//self.ticks)%16) < 16:
                        #if self.my_buffer.levels[track.pos[Modes.mTr.value],0+track.track_id] == 0:
                        #    self.my_buffer.led_set(track.pos[Modes.mTr.value]-1, 7-track.track_id, previous_step[track.track_id])
                        #    self.my_buffer.led_set(track.pos[Modes.mTr.value], 7-track.track_id, 15)
                        #    previous_step[track.track_id] = 0
                        #else: #toggle an already lit led as we pass over it
                        #    previous_step[track.track_id] = 15
                        #    self.my_buffer.led_set(track.pos[Modes.mTr.value], 7-track.track_id, 0)
                            #buffer.led_set(track.play_position, 0+track.track_id, 15)
                    #else:
                    #    self.my_buffer.led_set(self.current_track.pos[Modes.mTr.value], 7, 0)

            else:
                if self.k_mode.value < Modes.mScale.value : # all other modes except scale or pattern
                    if self.k_mod_mode == ModModes.modTime:
                        # light up the current time multiplier
                        self.my_buffer.led_row(0,7,np.roll((self.my_pos_buffer).astype(int),self.get_tmul_display(self.current_track.tmul[self.k_mode.value]),axis=1))
                    elif self.k_mod_mode == ModModes.modLoop:
                        print("track",self.current_track.track_id,"lstart",self.current_track.lstart[self.k_mode.value],"lend",self.current_track.lend[self.k_mode.value])
                        print("start",np.zeros(self.current_track.lstart[self.k_mode.value]).shape)
                        print("middle",np.ones(self.current_track.lend[self.k_mode.value]+1-self.current_track.lend[self.k_mode.value]).shape)
                        print("end",np.zeros(15-self.current_track.lend[self.k_mode.value]).shape)
                        self.my_buffer.led_row(0,7,np.block([np.zeros(self.current_track.lstart[self.k_mode.value],int),np.ones(self.current_track.lend[self.k_mode.value]+1-self.current_track.lstart[self.k_mode.value],int),np.zeros(15-self.current_track.lend[self.k_mode.value],int)]).tolist())
                        #    for i in range(16):
                        #        if i >= self.current_track.lstart[self.k_mode.value] and i <= self.current_track.lend[self.k_mode.value]:
                        #            self.my_buffer.led_set(i,7,15)
                        #        else:
                        #            self.my_buffer.led_set(i,7,0)
                    else:
                        if self.k_mode.value > Modes.mNote.value : # all other modes except note scale or pattern
                            self.my_buffer.led_row(0,7,np.array([self.current_track.tr])-np.roll((self.my_pos_buffer).astype(int),self.current_track.pos[self.k_mode.value]-1,axis=1))
                            self.my_buffer.led_row(0,7,np.array([self.current_track.tr])+np.roll((self.my_pos_buffer).astype(int),self.current_track.pos[self.k_mode.value],axis=1))
                        else:
                            self.my_buffer.led_row(0,7,np.roll((self.my_pos_buffer).astype(int),self.current_track.pos[self.k_mode.value],axis=1))
                        #self.my_buffer.led_map(0,0,(np.concatenate((np.asarray(np.split(self.my_buffer.levels,[7],axis=1)[0]),np.roll((self.my_pos_buffer).astype(int),self.current_track.pos[self.k_mode.value],axis=1).T,),axis=1)))
                elif self.k_mode == Modes.mPattern:
                    if self.k_mod_mode == ModModes.modTime:
                        #self.my_buffer.led_set(self.state.cue_div, 6, 15)
                        self.my_buffer.led_row(0, 6, self.my_buffer.levels.T[6]+np.roll((self.my_pos_buffer).astype(int),self.get_tmul_display(self.state.cue_div),axis=1))
                    else:
                        #if self.cue_pos > 0:
                        #    self.my_buffer.led_set(self.cue_pos-1, 6, 0) # set the previous cue indicator off
                        #else:
                        #    self.my_buffer.led_set(self.state.cue_steps, 6, 0) 
                        #self.my_buffer.led_set(self.cue_pos, 1, 15) #set the current cue indicator on
                        self.my_buffer.led_row(0, 6, np.roll((self.my_pos_buffer).astype(int),self.cue_pos,axis=1))



    def draw_notes_page(self):
        #self.my_buffer.led_set(5,0,0)
        #self.my_buffer.led_set(6,0,15)
        #self.my_buffer.led_set(7,0,0)
        #self.my_buffer.led_set(8,0,0)
        #self.my_buffer.led_set(9,0,0)
        #self.my_buffer.led_set(14,0,0)
        #self.my_buffer.led_set(15,0,0)
        #for x in range(self.grid.width):
        #    for y in range(1,self.grid.height): #ignore bottom row
        #        #render_pos = self.spanToGrid(x,y)
        #        if self.current_track.track_id == 0:
        #            self.my_buffer.led_set(x, y, self.current_pattern.step_ch1[y][x])
        #        elif self.current_track.track_id == 1:
        #            self.my_buffer.led_set(x, y, self.current_pattern.step_ch2[y][x])
        #        elif self.current_track.track_id == 2:
        #            self.my_buffer.led_set(x, y, self.current_pattern.step_ch3[y][x])
        #        elif self.current_track.track_id == 3:
        #            self.my_buffer.led_set(x, y, self.current_pattern.step_ch4[y][x])
        #for y in range(1,self.grid.height): #ignore bottom row
        #        if self.current_track.track_id == 0:
        #            self.my_buffer.led_row(0, y, self.current_pattern.step_ch1[y])
        #        elif self.current_track.track_id == 1:
        #            self.my_buffer.led_row(0, y, self.current_pattern.step_ch2[y])
        #        elif self.current_track.track_id == 2:
        #            self.my_buffer.led_row(0, y, self.current_pattern.step_ch3[y])
        #        elif self.current_track.track_id == 3:
        #            self.my_buffer.led_row(0, y, self.current_pattern.step_ch4[y])
        if self.current_track.track_id == 0:
            self.my_buffer.led_map(0, 0, np.asarray(self.current_pattern.step_ch1).T)
        elif self.current_track.track_id == 1:
            self.my_buffer.led_row(0, 0, np.asarray(self.current_pattern.step_ch2).T)
        elif self.current_track.track_id == 2:
            self.my_buffer.led_row(0, 0, np.asarray(self.current_pattern.step_ch3).T)
        elif self.current_track.track_id == 3:
            self.my_buffer.led_row(0, 0, np.asarray(self.current_pattern.step_ch4).T)
        self.draw_current_position()

    def draw_current_track_indicator(self):
        if self.current_track.track_id == 0:
            self.my_buffer.led_set(0,0,15) #set the channel 1 indicator on
            self.my_buffer.led_set(1,0,0)  #set the channel 2 indicator off
            self.my_buffer.led_set(2,0,0)  #set the channel 3 indicator off
            self.my_buffer.led_set(3,0,0)  #set the channel 4 indicator off
            #buffer.led_set(render_pos[0], render_pos[1], self.step_ch1[y][x] * 11 + highlight)
        elif self.current_track.track_id ==1:
            self.my_buffer.led_set(0,0,0)   #set the channel 1 indicator off
            self.my_buffer.led_set(1,0,15)  #set the channel 2 indicator on
            self.my_buffer.led_set(2,0,0)  #set the channel 3 indicator off
            self.my_buffer.led_set(3,0,0)  #set the channel 4 indicator off
            #buffer.led_set(render_pos[0], render_pos[1], self.step_ch2[y][x] * 11 + highlight)
        elif self.current_track.track_id == 2:
            self.my_buffer.led_set(0,0,0)   #set the channel 1 indicator off
            self.my_buffer.led_set(1,0,0)  #set the channel 2 indicator on
            self.my_buffer.led_set(2,0,15)  #set the channel 3 indicator off
            self.my_buffer.led_set(3,0,0)  #set the channel 4 indicator off
            #buffer.led_set(render_pos[0], render_pos[1], self.step_ch3[y][x] * 11 + highlight)
        elif self.current_track.track_id == 3:
            self.my_buffer.led_set(0,0,0)   #set the channel 1 indicator off
            self.my_buffer.led_set(1,0,0)  #set the channel 2 indicator on
            self.my_buffer.led_set(2,0,0)  #set the channel 3 indicator off
            self.my_buffer.led_set(3,0,15)  #set the channel 4 indicator off
            #buffer.led_set(render_pos[0], render_pos[1], self.step_ch4[y][x] * 11 + highlight)


    def draw_trigger_page(self):
        #draw polyphony toggles
        self.my_polyphony_toggle_buffer = np.concatenate((np.array([[self.current_pattern.tracks[0].polyphonic,self.current_pattern.tracks[1].polyphonic,self.current_pattern.tracks[2].polyphonic,self.current_pattern.tracks[3].polyphonic]]),[[0,0,0,0,0,0,0,0,0,0,0,0]]),axis=1)
        self.my_buffer.led_row(0,3,self.my_polyphony_toggle_buffer)

        #draw scale toggles & sync mode indicator
        #default sync mode display is 1 - but then update if needed
        sync_mode_display = np.array([[0,1,0,0,0,0,0,0,0,0,0,0]])
        if self.current_pattern.tracks[0].sync_mode == 1:
            sync_mode_display = np.array([[0,0,1,0,0,0,0,0,0,0,0,0]])
        elif self.current_pattern.tracks[0].sync_mode == 2:
            sync_mode_display = np.array([[0,0,0,1,0,0,0,0,0,0,0,0]])

        #draw scale toggles
        self.my_scale_toggle_buffer = np.concatenate((np.array([[self.current_pattern.tracks[0].scale_toggle,self.current_pattern.tracks[1].scale_toggle,self.current_pattern.tracks[2].scale_toggle,self.current_pattern.tracks[3].scale_toggle]]),sync_mode_display),axis=1)
        self.my_buffer.led_row(0,2,self.my_scale_toggle_buffer)

        #draw mute toggles
        self.my_mute_toggle_buffer = np.concatenate((np.array([[self.current_pattern.tracks[0].track_mute,self.current_pattern.tracks[1].track_mute,self.current_pattern.tracks[2].track_mute,self.current_pattern.tracks[3].track_mute]]),np.array([[0,0,0,0,0,0,0,0,0,0,0,0]])),axis=1)
        self.my_buffer.led_row(0,1,self.my_mute_toggle_buffer)

        # display triggers for each track
        self.my_buffer.led_row(0,7,np.array([self.current_pattern.tracks[0].tr]))
        self.my_buffer.led_row(0,6,np.array([self.current_pattern.tracks[1].tr]))
        self.my_buffer.led_row(0,5,np.array([self.current_pattern.tracks[2].tr]))
        self.my_buffer.led_row(0,4,np.array([self.current_pattern.tracks[3].tr]))

        #for x in range(self.grid.width):
        #    if x > 4 and x < 8: #clear the sync mode
        #        self.buffer.led_set(x, 3, 0) #display is inverted - as if to turn tracks "off" rather than turn mutes "on"
        #    for track in self.current_pattern.tracks:
                #buffer.led_set(x, 7-track.track_id, track.tr[x] * 15)
                # display scale toggle
        #        if x < 4:
        #            self.buffer.led_set(track.track_id, 2, track.scale_toggle * 15)
                    #print("track: ", track.track_id, "x: ", x, "scale toggle: ", track.scale_toggle)
        #            self.buffer.led_set(track.track_id, 1, (1-track.track_mute) * 15) #display is inverted - as if to turn tracks "off" rather than turn mutes "on"
        # display loop sync mode
        #self.buffer.led_set(5+self.current_track.sync_mode, 3, 15) #display is inverted - as if to turn tracks "off" rather than turn mutes "on"
        #print(buffer.levels)
        self.draw_current_position()

    def set_track_display(self):
        if self.current_track.track_id == 0:
            self.track_buffer = np.array([[1,0,0,0,0]])
        elif self.current_track.track_id == 1:
            self.track_buffer = np.array([[0,1,0,0,0]])
        elif self.current_track.track_id == 2:
            self.track_buffer = np.array([[0,0,1,0,0]])
        elif self.current_track.track_id == 3:
            self.track_buffer = np.array([[0,0,0,1,0]])

    def set_mode_display(self):
        if self.k_mode == Modes.mTr:
            self.mode_buffer = np.array([[1,0,0,0,0,0,0,0,0,0,0]])
        elif self.k_mode == Modes.mNote:
            self.mode_buffer = np.array([[0,1,0,0,0,0,0,0,0,0,0]])
        elif self.k_mode == Modes.mOct:
            self.mode_buffer = np.array([[0,0,1,0,0,0,0,0,0,0,0]])
        elif self.k_mode == Modes.mDur:
            self.mode_buffer = np.array([[0,0,0,1,0,0,0,0,0,0,0]])
        elif self.k_mode == Modes.mVel:
            self.mode_buffer = np.array([[0,0,0,0,1,0,0,0,0,0,0]])
        elif self.k_mode == Modes.mScale:
            self.mode_buffer = np.array([[0,0,0,0,0,0,0,0,0,1,0]])
        elif self.k_mode == Modes.mPattern:
            self.mode_buffer = np.array([[0,0,0,0,0,0,0,0,0,0,1]])

    def set_octave(self,x,octave):
        y = octave + 4
        #print("y",y)
        if y >= 4:
            positive = np.ones((1,y-2),int)
            blank_top_section = np.zeros((1,7-y),int)
            blank_bottom_section = np.zeros((1,3),int)
            octave_col = np.block([blank_bottom_section,positive,blank_top_section])
            #print(octave_col)
            self.my_buffer.led_col(x,0,octave_col[0])
        if y < 4:
            negative = np.ones((1,4-y),int)
            blank_top_section = np.zeros((1,4),int)
            blank_bottom_section = np.zeros((1,y),int)
            octave_col = np.block([blank_bottom_section,negative,blank_top_section])
            #print(octave_col)
            self.my_buffer.led_col(x,0,octave_col[0])

    def draw_octave_page(self):
        self.my_buffer.led_row(0,7,np.array([self.current_track.tr]))
        for x in range(self.grid.width):
            self.set_octave(x,self.current_track.octave[x])
        self.draw_current_position()

    def set_duration(self,x,duration):
        y = duration
        #print("y",y)
        positive = np.ones((1,y+1),int)
        #blank_top_section = np.zeros((1,7-y),int)
        blank_bottom_section = np.zeros((1,7-y),int)
        duration_col = np.block([blank_bottom_section,positive])
        #print(duration_col)
        self.my_buffer.led_col(x,0,duration_col[0])

    def draw_duration_page(self):
        #for x in range(self.grid.width):
        #    self.set_duration(x,self.current_track.duration[x])
        # more efficient rendering technique
        # convert duration values into binary representations and render directly, instead of using a for loop
        self.my_buffer.led_map(0,0,np.roll(np.unpackbits(np.invert((256-np.exp2(np.reshape(np.asarray(self.current_track.duration),(16,1)))).astype(np.uint8)),axis=1),-1,axis=1))
        self.my_buffer.led_row(0,7,np.array([self.current_track.tr]))
        self.draw_current_position()

    def set_velocity(self,x,velocity):
        y = velocity
        #print("y",y)
        positive = np.ones((1,y),int)
        blank_bottom_section = np.zeros((1,1),int)
        blank_top_section = np.zeros((1,7-y),int)
        velocity_col = np.block([blank_bottom_section,positive,blank_top_section])
        #print(velocity_col)
        self.my_buffer.led_col(x,0,velocity_col[0])

    def draw_velocity_page(self):
        #for x in range(self.grid.width):
        #    self.set_velocity(x,self.current_track.velocity[x])
        self.my_buffer.led_map(0,0,np.roll(np.fliplr(np.unpackbits(np.invert((256-np.exp2(np.reshape(np.asarray(self.current_track.velocity),(16,1)))).astype(np.uint8)),axis=1)),1,axis=1))
        self.my_buffer.led_row(0,7,np.array([self.current_track.tr]))
        self.draw_current_position()

    def draw_scale_page(self):
        #self.my_buffer.led_set(5,0,0)
        #self.my_buffer.led_set(6,0,0)
        #self.my_buffer.led_set(7,0,0)
        #self.my_buffer.led_set(8,0,0)
        #self.my_buffer.led_set(9,0,0)
        #self.my_buffer.led_set(14,0,15)
        #self.my_buffer.led_set(15,0,0)
        #self.my_buffer.led_set(15,0,0)
        #clear any previous scale
        #for ix in range (15):
        #    for iy in range (1,7):
        #        self.my_buffer.led_set(ix,iy, 0)
        # show the selected scale 
        self.my_buffer.led_set(self.cur_scale_id//6,self.cur_scale_id%6+1, 15)
        # set a transpose reference point
        self.my_buffer.led_set(7,1,15)
        #display the actual scale
        for sd in range (1,8):
            #self.my_buffer.led_set(7+self.cur_trans+self.current_preset.scale_data[self.cur_scale_id][sd],7-sd, 15)
            # set the scale note indicator for each row. - probably need to combine with the scale selection indicator above
            self.my_buffer.led_row(0, sd, self.my_buffer.levels.T[sd]+np.roll((self.my_pos_buffer).astype(int),7+self.cur_trans+self.current_preset.scale_data[self.cur_scale_id][sd],axis=1))
            #print("sd: ", sd, "scale val: ", self.scale_data[self.cur_scale_id][sd], "pos: ", 4+self.scale_data[self.cur_scale_id][sd],7-sd-1)
        #self.draw_current_position()

    def draw_pattern_page(self):
        #self.my_buffer.led_set(5,0,0)
        #self.my_buffer.led_set(6,0,0)
        #self.my_buffer.led_set(7,0,0)
        #self.my_buffer.led_set(8,0,0)
        #self.my_buffer.led_set(9,0,0)
        #self.my_buffer.led_set(14,0,0)
        #self.my_buffer.led_set(15,0,15)
        #for i in range(16):
        #    self.my_buffer.led_set(i,7,0)
        #self.my_buffer.led_set(self.current_pattern.pattern_id,7,15)
        self.my_buffer.led_row(0, 7, self.my_buffer.levels.T[7]+np.roll((self.my_pos_buffer).astype(int),self.current_pattern.pattern_id,axis=1))
        self.draw_current_position()

    def draw_mod_indicators(self):
        if self.k_mod_mode == ModModes.modLoop:
            self.my_buffer.led_set(10,0,15)
            self.my_buffer.led_set(11,0,0)
            self.my_buffer.led_set(12,0,0)
        elif self.k_mod_mode == ModModes.modTime:
            self.my_buffer.led_set(10,0,0)
            self.my_buffer.led_set(11,0,15)
            self.my_buffer.led_set(12,0,0)
        elif self.k_mod_mode == ModModes.modProb:
            self.my_buffer.led_set(10,0,0)
            self.my_buffer.led_set(11,0,0)
            self.my_buffer.led_set(12,0,15)

    def draw(self):
        if self.frame_dirty:
            #self.draw_current_track_indicator()
            #self.draw_mod_indicators()
            if self.k_mode == Modes.mTr:
                self.draw_trigger_page()
            elif self.k_mode == Modes.mNote:
                self.draw_notes_page()
            elif self.k_mode == Modes.mOct:
                self.draw_octave_page()
            elif self.k_mode == Modes.mDur:
                self.draw_duration_page()
            elif self.k_mode == Modes.mVel:
                self.draw_velocity_page()
            elif self.k_mode == Modes.mScale:
                self.draw_scale_page()
            elif self.k_mode == Modes.mPattern:
                self.draw_pattern_page()

            #assemble indicator row
            self.set_track_display()
            self.set_mode_display()
            indicator_row = np.block([self.track_buffer,self.mode_buffer])
            #split off the first row of the map and concatenate the remainder with the indicator row
            self.my_buffer.led_map(0,0,(np.concatenate((indicator_row.T,np.asarray(np.split(self.my_buffer.levels,[1,8],axis=1)[1])),axis=1)))
        self.grid.led_map(0,0,self.my_buffer.levels)
        #print(len(self.buffer.levels[0]))
        #print(self.buffer.levels)
        self.my_buffer.led_level_all(0)
        self.frame_dirty = False 

    def draw2(self):
        #print("drawing grid")
        if self.frame_dirty:
            my_buffer = monome.GridBuffer(self.grid.width, self.grid.height)

            if self.k_mode == Modes.mNote:
                my_buffer.led_set(5,7,0)
                my_buffer.led_set(6,7,15)
                my_buffer.led_set(7,7,0)
                my_buffer.led_set(8,7,0)
                my_buffer.led_set(9,7,0)
                my_buffer.led_set(14,7,0)
                my_buffer.led_set(15,7,0)
                for x in range(self.grid.width):
                    for y in range(1,self.grid.height-1): #ignore bottom row
                        #render_pos = self.spanToGrid(x,y)
                        if self.current_track.track_id == 0:
                            my_buffer.led_set(x, y, self.current_pattern.step_ch1[y][x])
                        elif self.current_track.track_id == 1:
                            my_buffer.led_set(x, y, self.current_pattern.step_ch2[y][x])
                        elif self.current_track.track_id == 2:
                            my_buffer.led_set(x, y, self.current_pattern.step_ch3[y][x])
                        elif self.current_track.track_id == 3:
                            my_buffer.led_set(x, y, self.current_pattern.step_ch4[y][x])
            elif self.k_mode == Modes.mOct:
                my_buffer.led_set(5,7,0)
                my_buffer.led_set(6,7,0)
                my_buffer.led_set(7,7,15)
                my_buffer.led_set(8,7,0)
                my_buffer.led_set(9,7,0)
                my_buffer.led_set(14,7,0)
                my_buffer.led_set(15,7,0)
                for x in range(self.grid.width):
                    #show the triggers for that track on the top row
                    my_buffer.led_set(x, 0, self.current_track.tr[x])
                    #if self.current_channel == 1:
                    #fill a column bottom up in the x position
                    current_oct = self.current_track.octave[x]
                    if current_oct >= 0:
                        #print("start = ", 1, "end = ", 4-current_oct)
                        for i in range (4-current_oct,5):
                            my_buffer.led_set(x, i, 15)
                            #print("current oct: ", current_oct, " drawing in row: ", i)
                    if current_oct < 0:
                        for i in range (4,5-current_oct):
                            my_buffer.led_set(x, i, 15)
                            #print("current oct: ", current_oct, " drawing in row: ", i)
            elif self.k_mode == Modes.mDur:
                my_buffer.led_set(5,7,0)
                my_buffer.led_set(6,7,0)
                my_buffer.led_set(7,7,0)
                my_buffer.led_set(8,7,15)
                my_buffer.led_set(9,7,0)
                my_buffer.led_set(14,7,0)
                my_buffer.led_set(15,7,0)
                for x in range(self.grid.width):
                    #show the triggers for that track on the top row
                    my_buffer.led_set(x, 0, self.current_track.tr[x])
                    #draw the accent toggles - this will move to a velocity page?
                    #if self.current_track.velocity[x]:
                    #    buffer.led_set(x, 7, 15)
                    #else:
                    #    buffer.led_set(x, 7, 0)
                    #if self.current_channel == 1:
                        #fill a column top down in the x position
                    for i in range (1,self.current_track.duration[x]+1): #ignore top row
                        my_buffer.led_set(x, i, 15)
                    for i in range (self.current_track.duration[x]+1,7): #ignore bottom row
                        my_buffer.led_set(x, i, 0)
                    #elif self.current_channel == 2:
                        #for i in range (1,self.current_pattern.tracks[1].duration[x]+1):
                        #    buffer.led_set(x, i, 15)
                        #for i in range (self.current_pattern.tracks[1].duration[x]+1,7):
                        #    buffer.led_set(x, i, 0)
            elif self.k_mode == Modes.mVel:
                my_buffer.led_set(5,7,0)
                my_buffer.led_set(6,7,0)
                my_buffer.led_set(7,7,0)
                my_buffer.led_set(8,7,0)
                my_buffer.led_set(9,7,15)
                my_buffer.led_set(14,7,0)
                my_buffer.led_set(15,7,0)
                for x in range(self.grid.width):
                    my_buffer.led_set(x, 0, self.current_track.tr[x])
                    for i in range (7-self.current_track.velocity[x],7): #ignore bottom row
                        my_buffer.led_set(x, i, 15)
                    for i in range (0,7-self.current_track.velocity[x]): #ignore top row
                        my_buffer.led_set(x, i, 0)
                    #show the triggers for that track on the top row
                    my_buffer.led_set(x, 0, self.current_track.tr[x])
                    #elif self.current_channel == 2:
                        #for i in range (1,self.current_pattern.tracks[1].duration[x]+1):
                        #    buffer.led_set(x, i, 15)
                        #for i in range (self.current_pattern.tracks[1].duration[x]+1,7):
                        #    buffer.led_set(x, i, 0)
            elif self.k_mode == Modes.mScale:
                my_buffer.led_set(5,7,0)
                my_buffer.led_set(6,7,0)
                my_buffer.led_set(7,7,0)
                my_buffer.led_set(8,7,0)
                my_buffer.led_set(9,7,0)
                my_buffer.led_set(14,7,15)
                my_buffer.led_set(15,7,0)
                my_buffer.led_set(15,7,0)
                #clear any previous scale
                for ix in range (15):
                    for iy in range (1,7):
                        my_buffer.led_set(ix,iy, 0)
                # show the selected scale 
                my_buffer.led_set(self.cur_scale_id//6,7-self.cur_scale_id%6-1, 15)
                # set a transpose reference point
                my_buffer.led_set(7,7,15)
                #display the actual scale
                for sd in range (1,8):
                    my_buffer.led_set(7+self.cur_trans+self.current_preset.scale_data[self.cur_scale_id][sd],7-sd, 15)
                    #print("sd: ", sd, "scale val: ", self.scale_data[self.cur_scale_id][sd], "pos: ", 4+self.scale_data[self.cur_scale_id][sd],7-sd-1)
            elif self.k_mode == Modes.mPattern:
                my_buffer.led_set(5,7,0)
                my_buffer.led_set(6,7,0)
                my_buffer.led_set(7,7,0)
                my_buffer.led_set(8,7,0)
                my_buffer.led_set(9,7,0)
                my_buffer.led_set(14,7,0)
                my_buffer.led_set(15,7,15)
                for i in range(16):
                    my_buffer.led_set(i,0,0)
                my_buffer.led_set(self.current_pattern.pattern_id,0,15)
            if self.k_mod_mode == ModModes.modLoop:
                my_buffer.led_set(10,7,15)
                my_buffer.led_set(11,7,0)
                my_buffer.led_set(12,7,0)
            elif self.k_mod_mode == ModModes.modTime:
                my_buffer.led_set(10,7,0)
                my_buffer.led_set(11,7,15)
                my_buffer.led_set(12,7,0)
            elif self.k_mod_mode == ModModes.modProb:
                my_buffer.led_set(10,7,0)
                my_buffer.led_set(11,7,0)
                my_buffer.led_set(12,7,15)

            # display the other track positions
            # I think this could all be simplified
            # change the bounds of the first if condition to match the
            # loop start and end points
            if self.k_mode == Modes.mTr:
                if self.k_mod_mode == ModModes.modTime:
                    for track in self.current_pattern.tracks:
                        for i in range(16):
                            my_buffer.led_set(i,0+track.track_id,0)
                        # light up the current time multiplier
                        my_buffer.led_set(track.tmul[self.k_mode.value], 0+track.track_id, 15)
                elif self.k_mod_mode == ModModes.modLoop:
                    for track in self.current_pattern.tracks:
                        for i in range(16):
                            if i >= track.lstart[Modes.mTr.value] and i <= track.lend[Modes.mTr.value]:
                                my_buffer.led_set(i,0+track.track_id,15)
                            else:
                                my_buffer.led_set(i,0+track.track_id,0)
                else:
                    previous_step = [0,0,0,0]
                    for track in self.current_pattern.tracks:
                        #track 1
                        if track.pos[Modes.mTr.value] >= track.lstart[Modes.mTr.value] and track.pos[Modes.mTr.value] <= track.lend[Modes.mTr.value]:
                        #if ((self.current_pos//self.ticks)%16) < 16:
                            if my_buffer.levels[track.pos[Modes.mTr.value],0+track.track_id] == 0:
                                my_buffer.led_set(track.pos[Modes.mTr.value]-1, 0+track.track_id, previous_step[track.track_id])
                                my_buffer.led_set(track.pos[Modes.mTr.value], 0+track.track_id, 15)
                                previous_step[track.track_id] = 0
                            else: #toggle an already lit led as we pass over it
                                previous_step[track.track_id] = 15
                                my_buffer.led_set(track.pos[Modes.mTr.value], 0+track.track_id, 0)
                                #buffer.led_set(track.play_position, 0+track.track_id, 15)
                        else:
                            my_buffer.led_set(self.current_track.pos[Modes.mTr.value], 0, 0)

            else:
                if self.k_mode.value < Modes.mScale.value : # all other modes except scale or pattern
                    if self.k_mod_mode == ModModes.modTime:
                        # capture top row ?
                        # blank the top row
                        for i in range(16):
                            my_buffer.led_set(i,7,0)
                        # light up the current time multiplier
                        my_buffer.led_set(self.current_track.tmul[self.k_mode.value], 7, 15)
                    elif self.k_mod_mode == ModModes.modLoop:
                            for i in range(16):
                                if i >= self.current_track.lstart[self.k_mode.value] and i <= self.current_track.lend[self.k_mode.value]:
                                    my_buffer.led_set(i,0,15)
                                else:
                                    my_buffer.led_set(i,0,0)
                    else:
                        #display play pcurrent_rowosition of current track & current parameter
                        previous_step = [0,0,0,0]
                        if my_buffer.levels[0+self.current_track.track_id][self.current_track.pos[self.k_mode.value]] == 0:
                            my_buffer.led_set(self.current_track.pos[self.k_mode.value]-1, 0, previous_step[self.current_track.track_id])
                            my_buffer.led_set(self.current_track.pos[self.k_mode.value], 0, 15)
                            previous_step[self.current_track.track_id] = 0
                        else: #toggle an already lit led as we pass over it
                            previous_step[self.current_track.track_id] = 15
                            my_buffer.led_set(self.current_track.pos[self.k_mode.value], 7, 0)
                elif self.k_mode == Modes.mPattern:
                    if self.k_mod_mode == ModModes.modTime:
                        my_buffer.led_set(self.state.cue_div, 6, 15)
                    else:
                        if self.cue_pos > 0:
                            my_buffer.led_set(self.cue_pos-1, 6, 0) # set the previous cue indicator off
                        else:
                            my_buffer.led_set(self.state.cue_steps, 6, 0) 
                        my_buffer.led_set(self.cue_pos, 1, 15) #set the current cue indicator on

                    #buffer.led_set(self.current_track.play_position, 0, 15)
                #else:
                #    buffer.led_set(self.current_track.pos[self.k_mode.value], 0, 0)

            # update grid
            #buffer.render(self.grid)
            self.grid.led_level_map(0,0,my_buffer.levels)
            self.frame_dirty = False

    def select_track(self, x, s):
        if x == 0:
            if self.k_mod_mode == ModModes.modTime:
                #reset all posititions to 0
                for track in self.current_pattern.tracks:
                    track.pos_reset = True
            else:
                print("Selected Track 1")
                self.current_track = self.current_pattern.tracks[0]
                self.current_track_id = self.current_pattern.tracks[0].track_id
                # track a ctrl key hold here
                self.ctrl_keys_held = self.ctrl_keys_held + (s * 2) - 1
                print("ctr_keys_held: ", self.ctrl_keys_held)
                if self.ctrl_keys_held == 1:
                    self.ctrl_keys_last.append(x)
                    print("ctr_keys_last: ", self.ctrl_keys_last)
        elif x == 1:
            print("Selected Track 2")
            self.current_track = self.current_pattern.tracks[1]
            self.current_track_id = self.current_pattern.tracks[1].track_id
        elif x == 2:
            print("Selected Track 3")
            self.current_track = self.current_pattern.tracks[2]
            self.current_track_id = self.current_pattern.tracks[2].track_id

            # track a ctrl key hold here
            self.ctrl_keys_held = self.ctrl_keys_held + (s * 2) - 1
            print("ctr_keys_held: ", self.ctrl_keys_held)
            if self.ctrl_keys_held == 2:
                self.ctrl_keys_last.append(x)
                print("ctr_keys_last: ", self.ctrl_keys_last)
        elif x == 3:
            print("Selected Track 4")
            self.current_track = self.current_pattern.tracks[3]
            self.current_track_id = self.current_pattern.tracks[3].track_id

    def select_mode(self, x, s):
        if x == 5:
            self.k_mode = Modes.mTr
            print("Selected:", self.k_mode)
        elif x == 6:
            self.k_mode = Modes.mNote
            print("Selected:", self.k_mode)
        elif x == 7:
            self.k_mode = Modes.mOct
            print("Selected:", self.k_mode)
        elif x == 8:
            self.k_mode = Modes.mDur
            print("Selected:", self.k_mode)
        elif x == 9:
            self.k_mode = Modes.mVel
            print("Selected:", self.k_mode)
        elif x == 14:
            self.k_mode = Modes.mScale
            print("Selected:", self.k_mode)
        elif x == 15:
            self.k_mode = Modes.mPattern
            print("Selected:", self.k_mode)
            # track a ctrl key hold here
            self.ctrl_keys_held = self.ctrl_keys_held + (s * 2) - 1
            print("ctr_keys_held: ", self.ctrl_keys_held)
            if self.ctrl_keys_held == 3:
                self.ctrl_keys_last.append(x)
                print("ctr_keys_last: ", self.ctrl_keys_last)
                self.ctrl_keys_held = 0
                if self.ctrl_keys_last == [0,2,15]:
                    del self.ctrl_keys_last[:]
                    self.disconnect()
                else:
                    del self.ctrl_keys_last[:]

    def select_modifier(self,x):
        if x == 10:
            self.k_mod_mode = ModModes.modLoop
            print("Selected:", self.k_mod_mode)
        elif x == 11:
            self.k_mod_mode = ModModes.modTime
            print("Selected:", self.k_mod_mode)
        elif x == 12:
            self.k_mod_mode = ModModes.modProb
            print("Selected:", self.k_mod_mode)

    def set_tmul_value(self, x):
        tmul_value = 0
        if x == 0:
            tmul_value = TICKS_32ND - 1
        elif x == 1:
            tmul_value = TICKS_SEXTUPLET - 1
        elif x == 2:
            tmul_value = TICKS_16TH - 1
        elif x == 3:
            tmul_value = TICKS_TRIPLET - 1
        elif x == 4:
            tmul_value = TICKS_8TH - 1
        elif x == 5:
            tmul_value = TICKS_QUARTER - 1
        elif x == 5:
            tmul_value = TICKS_HALF - 1
        elif x == 6:
            tmul_value = TICKS_WHOLE - 1
        elif x == 7:
            tmul_value = (TICKS_WHOLE * 2) - 1
        elif x == 8:
            tmul_value = (TICKS_WHOLE * 3) - 1
        elif x == 9:
            tmul_value = (TICKS_WHOLE * 4) - 1
        elif x == 10:
            tmul_value = (TICKS_WHOLE * 5) - 1
        elif x == 11:
            tmul_value = (TICKS_WHOLE * 6) - 1
        elif x == 12:
            tmul_value = (TICKS_WHOLE * 7) - 1
        elif x == 13:
            tmul_value = (TICKS_WHOLE * 8) - 1
        elif x == 14:
            tmul_value = (TICKS_WHOLE * 9) - 1
        elif x == 15:
            tmul_value = (TICKS_WHOLE * 10) - 1
        return tmul_value


    def set_global_time_multiplier(self,x,y):
        if self.k_mode == Modes.mTr and self.k_mod_mode == ModModes.modTime:
            # handle time multiplier setting
            if y > 3 and y < 8:
                if self.current_pattern.tracks[7-y].sync_mode == 0: # set the time multiplier for this parameter only
                    self.current_pattern.tracks[7-y].tmul[self.k_mode.value] = self.set_tmul_value(x)
                elif self.current_pattern.tracks[7-y].sync_mode == 1: #set the time multiplier for all parameters of this track
                    self.current_pattern.tracks[7-y].tmul[Modes.mTr.value] = self.set_tmul_value(x)
                    self.current_pattern.tracks[7-y].tmul[Modes.mNote.value] = self.set_tmul_value(x)
                    self.current_pattern.tracks[7-y].tmul[Modes.mOct.value] = self.set_tmul_value(x)
                    self.current_pattern.tracks[7-y].tmul[Modes.mDur.value] = self.set_tmul_value(x)
                    self.current_pattern.tracks[7-y].tmul[Modes.mVel.value] = self.set_tmul_value(x)

    def set_track_time_multiplier(self,x):
        #if self.k_mode == Modes.mTr: # enable this in all modes
        if self.k_mod_mode == ModModes.modTime:
            if self.current_track.sync_mode == 0: # set the time multiplier for this parameter only
                self.current_track.tmul[self.k_mode.value] = self.set_tmul_value(x)
            elif self.current_track.sync_mode == 1: #set the time multiplier for all parameters of this track
                self.current_track.tmul[Modes.mTr.value] = self.set_tmul_value(x)
                self.current_track.tmul[Modes.mNote.value] = self.set_tmul_value(x)
                self.current_track.tmul[Modes.mOct.value] = self.set_tmul_value(x)
                self.current_track.tmul[Modes.mDur.value] = self.set_tmul_value(x)
                self.current_track.tmul[Modes.mVel.value] = self.set_tmul_value(x)
            else:
                for track in self.current_pattern.tracks: # change time for all tracks
                    track.tmul[Modes.mTr.value] = self.set_tmul_value(x)
                    track.tmul[Modes.mNote.value] = self.set_tmul_value(x)
                    track.tmul[Modes.mOct.value] = self.set_tmul_value(x)
                    track.tmul[Modes.mDur.value] = self.set_tmul_value(x)
                    track.tmul[Modes.mVel.value] = self.set_tmul_value(x)
            print("tmul: ", self.k_mode, self.current_track.tmul[Modes.mTr.value])

    def set_track_settings(self,x,y):
        if self.k_mode == Modes.mTr:
            #print("Trigger page key:", x, y)
            if y == 3 and x < 4:
                self.current_pattern.tracks[x].polyphonic ^= 1
                print ("toggling polyphonic for track: ", x)
            if y == 2 and x < 4:
                self.current_pattern.tracks[x].scale_toggle ^= 1
                print ("toggling scale for track: ", x)
            if y == 1 and x < 4:
                self.current_pattern.tracks[x].track_mute ^= 1
                print ("toggling mute for track: ", x)
            if y == 2 and x > 4 and x < 8: # set the sync mode for all tracks
                self.current_pattern.tracks[0].sync_mode = x-5
                self.current_pattern.tracks[1].sync_mode = x-5
                self.current_pattern.tracks[2].sync_mode = x-5
                self.current_pattern.tracks[3].sync_mode = x-5
                print ("sync mode: ", x-5)

    def note_entry(self, x, y):
        if self.k_mode == Modes.mNote:
            if self.current_track.track_id == 0:
                self.current_pattern.step_ch1[y][x] ^= 1
            elif self.current_track.track_id == 1:
                self.current_pattern.step_ch2[y][x] ^= 1
            elif self.current_track.track_id == 2:
                self.current_pattern.step_ch3[y][x] ^= 1
            else:
                self.current_pattern.step_ch4[y][x] ^= 1
            if y not in self.current_track.note[x]:
                self.current_track.note[x].append(y)
                print("append: ", y, "at ", x)
            else:
                self.current_track.note[x].remove(y)
                #print("remove: ", y, "at ", x)
            if self.current_track.duration[x] == 0:
                self.current_track.duration[x] = 1
            # toggle the trigger if there are no notes
            if len(self.current_track.note[x]) > 0:
                self.current_track.tr[x] = 1
                #print("note len: ", self.current_track.note[x])
            else:
                self.current_track.tr[x] = 0
                #print("note len: ", self.current_track.note[x])

            #if self.current_track.tr[x] == 0:
            #    self.current_track.duration[x] = 0 # change this when param_sync is off
            #else:
            #    self.step_ch2[7-y][x] ^= 1
            #    self.current_pattern.tracks[1].note[x] = y
            #    self.current_pattern.tracks[1].duration[x] = 1
            #    self.current_pattern.tracks[1].tr[x] ^= 1
            #self.draw()
            self.frame_dirty = True

    def duration_entry(self, x, y):
        if self.k_mode == Modes.mDur:
            # add loop setting code based on loop mod
            # add time setting code based on time mod
            # add probability setting based on prob mod - default to standard duration if prob comes up "false"?
            self.current_track.duration[x] = 7-y
            print("grid_key = ", y, "duration = ", self.current_track.duration[x])
            self.frame_dirty = True 

    def octave_entry(self, x, y):
        if self.k_mode == Modes.mOct: 
            #if self.current_channel == 1:
            if y < 7 and y > 0:
                self.current_track.octave[x] = y-4
                print("grid_key = ", y, "octave = ", self.current_track.octave[x])
            #else:
            #    if y < 6 and y > 0:
            #        self.current_pattern.tracks[1].octave[x] = y-3
            #self.draw()
            self.frame_dirty = True 

    def velocity_entry(self, x, y):
        if self.k_mode == Modes.mVel:
            # add loop setting code based on loop mod
            # add time setting code based on time mod
            # add probability setting based on prob mod - default to standard velocity if prob comes up "false"?
            self.current_track.velocity[x] = y
            print("entered velocity: ", self.current_track.velocity[x])
            self.frame_dirty = True 

    def scale_entry(self, x, y):
        if self.k_mode == Modes.mScale:
            if x < 3:
                if y < 7 and y > 0:
                    self.cur_scale_id = y-1+x*6
                    self.calc_scale(self.cur_scale_id)
                    #print("selected scale: ", self.cur_scale_id)
            else:
                # transpose the scale up or down by semitones from the mid point (col 7)
                self.cur_trans = x-7
                self.calc_scale(self.cur_scale_id)
            self.frame_dirty = True 

    def preset_entry(self, x, y, s):
        if self.k_mode == Modes.mPattern:
            if y == 6:
                if self.k_mod_mode == ModModes.modTime:
                    self.state.cue_div = self.set_tmul_value(x)
                else:
                    self.state.cue_steps = x
            if x < 3:
                if y < 6 and y > 1:
                    self.state.current_preset_id = y-1+x*4
                    self.current_preset = self.state.presets[self.state.current_preset_id]
                    #print("selected preset: ", self.state.current_preset_id)
            #self.draw()
            self.frame_dirty = True 
            if y == 7:
                self.keys_held = self.keys_held + (s * 2) - 1
                self.key_last.append(x)
                print("pattern page keys_held: ", self.keys_held, self.key_last, s)
                if s == 1 and self.keys_held == 1:
                    if self.state.cue_steps == 0: #change pattern immediately
                        self.current_preset.current_pattern = x
                        self.current_pattern = self.current_preset.patterns[self.current_preset.current_pattern]
                        self.current_track = self.current_pattern.tracks[self.current_track_id]
                    else:
                        self.cue_pat_next = x+1
                elif s == 1 and self.keys_held == 2:
                    print("copying pattern ", self.key_last[0],"to ", x)
                    self.current_preset.patterns[x] = copy.deepcopy(self.current_preset.patterns[self.key_last[0]])
                    self.current_preset.patterns[x].pattern_id = x #need to set the pattern id again after deep copy
                    self.keys_held = 0
                    del self.key_last[:]
                else:
                    self.keys_held = 0
                    del self.key_last[:]
               # print("selected pattern: ", self.current_preset.current_pattern)

    def on_grid_key(self, x, y, s):
        print(x,y)
        # handle bottom row controls
        if s ==1 and y == 0:
            #select track
            self.select_track(x,s)
            #select mode
            self.select_mode(x,s)
            self.select_modifier(x)
        elif s == 0 and y == 0 and (x == 10 or x == 11 or x == 12):
                self.k_mod_mode = ModModes.modNone
        elif s == 0 and y == 0:
            self.ctrl_keys_held = 0
            del self.ctrl_keys_last[:]
        elif s == 1 and y > 0:
            # preset entry
            self.preset_entry(x,y,s)
            self.set_global_time_multiplier(x,y)
            if y == 7: #handle top row interactions
                self.set_track_time_multiplier(x)
            if y < 7:
                #handle various track settings (scale, mute)
                self.set_track_settings(x,y)
                # Note entry
                self.note_entry(x,y)
                # octave entry
                self.octave_entry(x,y)
                # duration entry
                self.duration_entry(x,y)
                # velocity entry
                self.velocity_entry(x,y)
                # scale entry
                self.scale_entry(x,y)
            elif y == 7: #switch to require modLoop? - shift to be inside each parameter
                self.keys_held = self.keys_held + (s * 2) - 1
                print("keys_held: ", self.keys_held)
                # cut
                if s == 1 and self.keys_held == 1 and self.k_mod_mode == ModModes.modLoop:
                    self.cutting = True
                    #self.current_track.next_position = x #change to be per parameter next
                    #self.current_track.loop_last = x #change to be per parameter last
                    self.current_track.next_pos[self.k_mode.value]= x #change to be per parameter next
                    self.current_track.last_pos[self.k_mode.value] = x
                    print("track_last: ", self.current_track.last_pos[self.k_mode.value])
                    print("cutting: ", self.cutting)
                # set loop points
                elif s == 1 and self.keys_held == 2 and self.cutting == True:
                    if self.current_track.last_pos[self.k_mode.value] < x: # don't wrap around, for now
                        #self.current_track.loop_start = self.current_track.loop_last #change to per parameter lstart
                        self.current_track.lstart[self.k_mode.value] = self.current_track.last_pos[self.k_mode.value]#change to per parameter lstart
                        print("track_lstart: ", self.current_track.lstart[self.k_mode.value])
                        #self.current_track.loop_end = x #change to per parameter lend: self.current_track.lend[self.k_mode.value] = x
                        self.current_track.lend[self.k_mode.value] = x #change to per parameter lend: self.current_track.lend[self.k_mode.value] = x
                        print("key_lend: ", self.current_track.lend[self.k_mode.value])
                        self.keys_held = 0
                        self.cutting = False
                        print("cutting: ", self.cutting)
                    else:
                        self.keys_held = 0
                else:
                    self.keys_held = 0
                    #print("loop start: ", self.loop_start[self.current_track], "end: ", self.loop_end[self.current_track])
        else:
            self.keys_held = 0
            del self.key_last[:]

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

