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
            self.frame_dirty = True #if nothing else has happend, at least the position has moved
            self.draw()
            yield from self.clock.sync(self.ticks//2)
            self.current_pos = yield from self.clock.sync()
            #print(self.current_pos%16)
            #led_pos = self.current_pos%16
            #self.grid.led_set(led_pos,0,1)
            #self.grid.led_set((led_pos-1)%16,0,0)
            #self.grid.led_set((led_pos-2)%16,0,0)
            #self.grid.led_set((led_pos-3)%16,0,0)


    def draw(self):
        if self.frame_dirty:
            print("drawing grid")
            buffer = monome.LedBuffer(self.width, self.height)

            if self.current_track.track_id == 0:
                buffer.led_level_set(0,7,15) #set the channel 1 indicator on
                buffer.led_level_set(1,7,0)  #set the channel 2 indicator off
                buffer.led_level_set(2,7,0)  #set the channel 3 indicator off
                buffer.led_level_set(3,7,0)  #set the channel 4 indicator off
                #buffer.led_level_set(render_pos[0], render_pos[1], self.step_ch1[y][x] * 11 + highlight)
            elif self.current_track.track_id ==1:
                buffer.led_level_set(0,7,0)   #set the channel 1 indicator off
                buffer.led_level_set(1,7,15)  #set the channel 2 indicator on
                buffer.led_level_set(2,7,0)  #set the channel 3 indicator off
                buffer.led_level_set(3,7,0)  #set the channel 4 indicator off
                #buffer.led_level_set(render_pos[0], render_pos[1], self.step_ch2[y][x] * 11 + highlight)
            elif self.current_track.track_id == 2:
                buffer.led_level_set(0,7,0)   #set the channel 1 indicator off
                buffer.led_level_set(1,7,0)  #set the channel 2 indicator on
                buffer.led_level_set(2,7,15)  #set the channel 3 indicator off
                buffer.led_level_set(3,7,0)  #set the channel 4 indicator off
                #buffer.led_level_set(render_pos[0], render_pos[1], self.step_ch3[y][x] * 11 + highlight)
            elif self.current_track.track_id == 3:
                buffer.led_level_set(0,7,0)   #set the channel 1 indicator off
                buffer.led_level_set(1,7,0)  #set the channel 2 indicator on
                buffer.led_level_set(2,7,0)  #set the channel 3 indicator off
                buffer.led_level_set(3,7,15)  #set the channel 4 indicator off
                #buffer.led_level_set(render_pos[0], render_pos[1], self.step_ch4[y][x] * 11 + highlight)
            if self.k_mode == Modes.mTr:
                buffer.led_level_set(5,7,15) #set the channel 1 indicator on
                buffer.led_level_set(6,7,0)  #set the channel 2 indicator off
                buffer.led_level_set(7,7,0)  #set the channel 3 indicator off
                buffer.led_level_set(8,7,0)  #set the channel 4 indicator off
                buffer.led_level_set(9,7,0)
                buffer.led_level_set(14,7,0)
                buffer.led_level_set(15,7,0)

                # display triggers for each track
                for x in range(self.width):
                    if x > 4 and x < 8: #clear the sync mode
                        buffer.led_level_set(x, 5, 0) #display is inverted - as if to turn tracks "off" rather than turn mutes "on"
                    for track in self.current_pattern.tracks:
                        buffer.led_level_set(x, 0+track.track_id, track.tr[x] * 15)
                        # display scale toggle
                        if x < 4:
                            buffer.led_level_set(track.track_id, 5, track.scale_toggle * 15)
                            #print("track: ", track.track_id, "x: ", x, "scale toggle: ", track.scale_toggle)
                            buffer.led_level_set(track.track_id, 6, (1-track.track_mute) * 15) #display is inverted - as if to turn tracks "off" rather than turn mutes "on"
                # display loop sync mode
                buffer.led_level_set(5+self.current_track.sync_mode, 5, 15) #display is inverted - as if to turn tracks "off" rather than turn mutes "on"
            elif self.k_mode == Modes.mNote:
                buffer.led_level_set(5,7,0)
                buffer.led_level_set(6,7,15)
                buffer.led_level_set(7,7,0)
                buffer.led_level_set(8,7,0)
                buffer.led_level_set(9,7,0)
                buffer.led_level_set(14,7,0)
                buffer.led_level_set(15,7,0)
                for x in range(self.width):
                    for y in range(1,self.height-1): #ignore bottom row
                        #render_pos = self.spanToGrid(x,y)
                        if self.current_track.track_id == 0:
                            buffer.led_level_set(x, y, self.current_pattern.step_ch1[y][x] * 15 )
                        elif self.current_track.track_id == 1:
                            buffer.led_level_set(x, y, self.current_pattern.step_ch2[y][x] * 15 )
                        elif self.current_track.track_id == 2:
                            buffer.led_level_set(x, y, self.current_pattern.step_ch3[y][x] * 15 )
                        elif self.current_track.track_id == 3:
                            buffer.led_level_set(x, y, self.current_pattern.step_ch4[y][x] * 15 )
            elif self.k_mode == Modes.mOct:
                buffer.led_level_set(5,7,0)
                buffer.led_level_set(6,7,0)
                buffer.led_level_set(7,7,15)
                buffer.led_level_set(8,7,0)
                buffer.led_level_set(9,7,0)
                buffer.led_level_set(14,7,0)
                buffer.led_level_set(15,7,0)
                for x in range(self.width):
                    #show the triggers for that track on the top row
                    buffer.led_level_set(x, 0, self.current_track.tr[x] * 15)
                    #if self.current_channel == 1:
                    #fill a column bottom up in the x position
                    current_oct = self.current_track.octave[x]
                    if current_oct >= 0:
                        #print("start = ", 1, "end = ", 4-current_oct)
                        for i in range (4-current_oct,5):
                            buffer.led_level_set(x, i, 15)
                            #print("current oct: ", current_oct, " drawing in row: ", i)
                    if current_oct < 0:
                        for i in range (4,5-current_oct):
                            buffer.led_level_set(x, i, 15)
                            #print("current oct: ", current_oct, " drawing in row: ", i)
            elif self.k_mode == Modes.mDur:
                buffer.led_level_set(5,7,0)
                buffer.led_level_set(6,7,0)
                buffer.led_level_set(7,7,0)
                buffer.led_level_set(8,7,15)
                buffer.led_level_set(9,7,0)
                buffer.led_level_set(14,7,0)
                buffer.led_level_set(15,7,0)
                for x in range(self.width):
                    #show the triggers for that track on the top row
                    buffer.led_level_set(x, 0, self.current_track.tr[x] * 15)
                    #draw the accent toggles - this will move to a velocity page?
                    #if self.current_track.velocity[x]:
                    #    buffer.led_level_set(x, 0, 15)
                    #else:
                    #    buffer.led_level_set(x, 0, 0)
                    #if self.current_channel == 1:
                        #fill a column top down in the x position
                    for i in range (1,self.current_track.duration[x]+1): #ignore top row
                        buffer.led_level_set(x, i, 15)
                    for i in range (self.current_track.duration[x]+1,7): #ignore bottom row
                        buffer.led_level_set(x, i, 0)
                    #elif self.current_channel == 2:
                        #for i in range (1,self.current_pattern.tracks[1].duration[x]+1):
                        #    buffer.led_level_set(x, i, 15)
                        #for i in range (self.current_pattern.tracks[1].duration[x]+1,7):
                        #    buffer.led_level_set(x, i, 0)
            elif self.k_mode == Modes.mVel:
                buffer.led_level_set(5,7,0)
                buffer.led_level_set(6,7,0)
                buffer.led_level_set(7,7,0)
                buffer.led_level_set(8,7,0)
                buffer.led_level_set(9,7,15)
                buffer.led_level_set(14,7,0)
                buffer.led_level_set(15,7,0)
                for x in range(self.width):
                    buffer.led_level_set(x, 0, self.current_track.tr[x] * 15)
                    for i in range (7-self.current_track.velocity[x],7): #ignore bottom row
                        buffer.led_level_set(x, i, 15)
                    for i in range (0,7-self.current_track.velocity[x]): #ignore top row
                        buffer.led_level_set(x, i, 0)
                    #show the triggers for that track on the top row
                    buffer.led_level_set(x, 0, self.current_track.tr[x] * 15)
                    #elif self.current_channel == 2:
                        #for i in range (1,self.current_pattern.tracks[1].duration[x]+1):
                        #    buffer.led_level_set(x, i, 15)
                        #for i in range (self.current_pattern.tracks[1].duration[x]+1,7):
                        #    buffer.led_level_set(x, i, 0)
            elif self.k_mode == Modes.mScale:
                buffer.led_level_set(5,7,0)
                buffer.led_level_set(6,7,0)
                buffer.led_level_set(7,7,0)
                buffer.led_level_set(8,7,0)
                buffer.led_level_set(9,7,0)
                buffer.led_level_set(14,7,15)
                buffer.led_level_set(15,7,0)
                buffer.led_level_set(15,7,0)
                #clear any previous scale
                for ix in range (15):
                    for iy in range (1,7):
                        buffer.led_level_set(ix,iy, 0)
                # show the selected scale 
                buffer.led_level_set(self.cur_scale_id//6,7-self.cur_scale_id%6-1, 15)
                # set a transpose reference point
                buffer.led_level_set(7,7,15)
                #display the actual scale
                for sd in range (1,8):
                    buffer.led_level_set(7+self.cur_trans+self.current_preset.scale_data[self.cur_scale_id][sd],7-sd, 15)
                    #print("sd: ", sd, "scale val: ", self.scale_data[self.cur_scale_id][sd], "pos: ", 4+self.scale_data[self.cur_scale_id][sd],7-sd-1)
            elif self.k_mode == Modes.mPattern:
                buffer.led_level_set(5,7,0)
                buffer.led_level_set(6,7,0)
                buffer.led_level_set(7,7,0)
                buffer.led_level_set(8,7,0)
                buffer.led_level_set(9,7,0)
                buffer.led_level_set(14,7,0)
                buffer.led_level_set(15,7,15)
                for i in range(16):
                    buffer.led_level_set(i,0,0)
                buffer.led_level_set(self.current_pattern.pattern_id,0,15)
            if self.k_mod_mode == ModModes.modLoop:
                buffer.led_level_set(10,7,15)
                buffer.led_level_set(11,7,0)
                buffer.led_level_set(12,7,0)
            elif self.k_mod_mode == ModModes.modTime:
                buffer.led_level_set(10,7,0)
                buffer.led_level_set(11,7,15)
                buffer.led_level_set(12,7,0)
            elif self.k_mod_mode == ModModes.modProb:
                buffer.led_level_set(10,7,0)
                buffer.led_level_set(11,7,0)
                buffer.led_level_set(12,7,15)

            # draw trigger bar and on-states
    #        for x in range(self.width):
    #            buffer.led_level_set(x, 6, 4)

    #        for y in range(6):
    #            if self.step_ch1[y][self.play_position] == 1:
    #                buffer.led_level_set(self.play_position, 6, 15)

            # draw play position
            #current_pos = yield from self.clock.sync()
            #print("runcible:",(self.current_pos//self.ticks)%16)
            #render_pos = self.spanToGrid(self.play_position, 0)
            #if ((self.current_pos//self.ticks)%16) < 16:
    #           print("Pos",self.play_position)
            #    buffer.led_level_set(render_pos[0], render_pos[1], 15)
            #else:
            #    buffer.led_level_set(render_pos[0], render_pos[1], 0) # change this to restore the original state of the led

            # display the other track positions
            # I think this could all be simplified
            # change the bounds of the first if condition to match the
            # loop start and end points
            if self.k_mode == Modes.mTr:
                if self.k_mod_mode == ModModes.modTime:
                    for track in self.current_pattern.tracks:
                        for i in range(16):
                            buffer.led_level_set(i,0+track.track_id,0)
                        # light up the current time multiplier
                        buffer.led_level_set(track.tmul[self.k_mode.value], 0+track.track_id, 15)
                elif self.k_mod_mode == ModModes.modLoop:
                    for track in self.current_pattern.tracks:
                        for i in range(16):
                            if i >= track.lstart[Modes.mTr.value] and i <= track.lend[Modes.mTr.value]:
                                buffer.led_level_set(i,0+track.track_id,15)
                            else:
                                buffer.led_level_set(i,0+track.track_id,0)
                else:
                    previous_step = [0,0,0,0]
                    for track in self.current_pattern.tracks:
                        #track 1
                        if track.pos[Modes.mTr.value] >= track.lstart[Modes.mTr.value] and track.pos[Modes.mTr.value] <= track.lend[Modes.mTr.value]:
                        #if ((self.current_pos//self.ticks)%16) < 16:
                            if buffer.levels[0+track.track_id][track.pos[Modes.mTr.value]] == 0:
                                buffer.led_level_set(track.pos[Modes.mTr.value]-1, 0+track.track_id, previous_step[track.track_id])
                                buffer.led_level_set(track.pos[Modes.mTr.value], 0+track.track_id, 15)
                                previous_step[track.track_id] = 0
                            else: #toggle an already lit led as we pass over it
                                previous_step[track.track_id] = 15
                                buffer.led_level_set(track.pos[Modes.mTr.value], 0+track.track_id, 0)
                                #buffer.led_level_set(track.play_position, 0+track.track_id, 15)
                        else:
                            buffer.led_level_set(self.current_track.pos[Modes.mTr.value], 0, 0)

            else:
                if self.k_mode.value < Modes.mScale.value : # all other modes except scale or pattern
                    if self.k_mod_mode == ModModes.modTime:
                        # capture top row ?
                        # blank the top row
                        for i in range(16):
                            buffer.led_level_set(i,0,0)
                        # light up the current time multiplier
                        buffer.led_level_set(self.current_track.tmul[self.k_mode.value], 0, 15)
                    elif self.k_mod_mode == ModModes.modLoop:
                            for i in range(16):
                                if i >= self.current_track.lstart[self.k_mode.value] and i <= self.current_track.lend[self.k_mode.value]:
                                    buffer.led_level_set(i,0,15)
                                else:
                                    buffer.led_level_set(i,0,0)
                    else:
                        #display play pcurrent_rowosition of current track & current parameter
                        previous_step = [0,0,0,0]
                        if buffer.levels[0+self.current_track.track_id][self.current_track.pos[self.k_mode.value]] == 0:
                            buffer.led_level_set(self.current_track.pos[self.k_mode.value]-1, 0, previous_step[self.current_track.track_id])
                            buffer.led_level_set(self.current_track.pos[self.k_mode.value], 0, 15)
                            previous_step[self.current_track.track_id] = 0
                        else: #toggle an already lit led as we pass over it
                            previous_step[self.current_track.track_id] = 15
                            buffer.led_level_set(self.current_track.pos[self.k_mode.value], 0, 0)
                elif self.k_mode == Modes.mPattern:
                    if self.k_mod_mode == ModModes.modTime:
                        buffer.led_level_set(self.state.cue_div, 1, 15)
                    else:
                        if self.cue_pos > 0:
                            buffer.led_level_set(self.cue_pos-1, 1, 0) # set the previous cue indicator off
                        else:
                            buffer.led_level_set(self.state.cue_steps, 1, 0) 
                        buffer.led_level_set(self.cue_pos, 1, 15) #set the current cue indicator on

                    #buffer.led_level_set(self.current_track.play_position, 0, 15)
                #else:
                #    buffer.led_level_set(self.current_track.pos[self.k_mode.value], 0, 0)

            # update grid
            buffer.render(self.grid)
            self.frame_dirty = False 


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

