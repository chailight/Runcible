#! /usr/bin/env python3
#RUNCIBLE - a raspberry pi / python sequencer for spanned 40h monomes inspired by Ansible Kria
#TODO:
#fix clear all on disconnect
#fix hanging notes on sequencer stop? how? either note creation becomes atomic or else there's a midi panic that gets called when the clock stops? maybe just close the midi stream?
#fix play position display on trigger screen so it's easier to follow - basically turn off an led that is on and remember to turn it back on again at the next step
#add mutes per channel - long press on the channel? - maybe channel mutes on trigger page - maybe also per row mutes somewhere?
#add note mutes for drum channel?
#add input/display for probability, as per kria
#enable a per channel transpose setting? 
#add timing modification
#make looping independent for each parameter
#add scale editing 
#add preset copy
#adjust preset selection to allow for meta sequencing
#fix display of current preset
#add persistence of presets
#fix cutting - has to do with keys held
#enable looping around the end of the loop start_loop is higher than end_loop
#add pattern cue timer
#add meta mode (pattern sequencing)
#consider per row velocity settings for polyphonic tracks
#adjust use of duration settings 1/8, 1/16 & 1/32 notes?  (6 duration positions = 1/32, 1/16, 1/8, 1/4, 1/2, 1)
#make note entry screen monophonic? - clear off other notes in that column if new note is entered - this should be configurable maybe on trigger page?
#add settings screen with other adjustments like midi channel for each track?
#fix pauses - network? other processes?

import pickle
import os
import sys
import asyncio
import monome
import spanned_monome
import clocks
#import synths
#import pygame
#import pygame.midi
import rtmidi2
#from pygame.locals import *
from enum import Enum

def cancel_task(task):
    if task:
        task.cancel()

class Modes(Enum):
    mTr = 1
    mNote = 2
    mOct = 3
    mDur = 4
    mScale = 5
    mPattern = 6
    mVel = 7

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

class Track:
    def __init__(self,track_id):
        self.num_params = 4
        #self.tr = [[0] for i in range(16)]
        self.tr = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]
        self.octave = [0 for i in range(16)]
        self.note = [list() for i in range(16)]
        self.duration = [1 for i in range(16)]
        self.velocity = [3 for i in range(16)]
        self.params = [[0] * self.num_params for i in range (16)] #initialise a 4x16 array
        self.dur_mul = 1; #duration multiplier
        self.lstart = [[0] * self.num_params]
        self.lend = [[15] * self.num_params]
        self.swap = [[0] * self.num_params]
        self.tmul = [[0] * self.num_params]
        self.pos = [[0] * self.num_params for i in range(4)] #position for each parameter in each track
        self.pos_mul = [[0] * self.num_params for i in range(4)] #something to do with the time multiplier
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

class Pattern:
    def __init__(self,pattern_id):
        self.pattern_id = pattern_id
        self.tracks = [Track(i) for i in range(4)]
        self.step_ch1 = [[0 for col in range(16)] for row in range(8)] #used for display of notes
        self.step_ch2 = [[0 for col in range(16)] for row in range(8)]
        self.step_ch3 = [[0 for col in range(16)] for row in range(8)]
        self.step_ch4 = [[0 for col in range(16)] for row in range(8)]
        #default scales - all starting at middle C


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

class State:
    def __init__(self):
        self.clock_period = 0
        self.current_preset_id = 0
        self.note_sync = True
        self.loop_sync = 0
        self.cue_div = 0
        self.cue_steps = 0
        self.meta = 0
        self.presets = [Preset() for i in range(15)]

#runcible sequencer, based on ansible kria
class Runcible(spanned_monome.VirtualGrid):
    def __init__(self, clock, ticks, midi_out,channel_out,clock_out,other):
        super().__init__('runcible')
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
        #call ready() directly because virtual device doesn't get triggered
        self.pickle_file_path = "/home/pi/monome/runcible.pickle" 
        self.ready()

    def ready(self):
        print ("using grid on port :%s" % self.id)
        self.current_pos = 0
      #  self.current_pattern.step_ch1 = [[0 for col in range(self.width)] for row in range(self.height)] #used for display of notes
      #  self.current_pattern.step_ch2 = [[0 for col in range(self.width)] for row in range(self.height)]
      #  self.current_pattern.step_ch3 = [[0 for col in range(self.width)] for row in range(self.height)]
      #  self.current_pattern.step_ch4 = [[0 for col in range(self.width)] for row in range(self.height)]
        self.play_position = [0,0,0,0] # one position for each track
        #self.fine_play_position = 0
        self.next_position = [0,0,0,0]
        self.cutting = False
        self.loop_start = [0,0,0,0]
        self.loop_end = [self.width - 1, self.width -1, self.width -1, self.width -1]
        self.loop_length = [self.width, self.width, self.width, self.width]
        self.keys_held = 0
        self.key_last = [0,0,0,0]
        if os.path.isfile(self.pickle_file_path):
            self.restore_state()
        self.current_preset = self.state.presets[0]
        self.current_pattern = self.current_preset.patterns[self.current_preset.current_pattern]
        self.current_track = self.current_pattern.tracks[0]
        self.current_track_id = self.current_pattern.tracks[0].track_id
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
        self.calc_scale(self.cur_scale_id)
        asyncio.async(self.play())

    def disconnect(self):
        self.save_state()
        super().disconnect()

    @asyncio.coroutine
    def play(self):
        self.current_pos = yield from self.clock.sync()
        for t in self.current_pattern.tracks:
            #self.loop_length[t] = abs(self.loop_end[self.current_track] - self.loop_start[t])+1
            t.loop_length = abs(t.loop_end - t.loop_start)+1
            t.play_position = (self.current_pos//self.ticks)%t.loop_length + t.loop_start
        #self.fine_play_position = self.current_pos%96
        #self.fine_play_position = self.play_position
        while True:
        #    for t in range(4):
            #t = self.current_track
            #print(self.clock.bpm,self.play_position, self.current_pos%64)
        #    if ((self.current_pos//self.ticks)%16) < 16:
            #if t.play_position  < 16:
            #print("G1:",(self.current_pos//self.ticks)%16)
            self.draw()
            # TRIGGER SOMETHING
            #ch1_note = None
            #ch2_note = None
            #for y in range(self.height): #re-enable this for polyphonic tracks
                #print("y:",y, "pos:", self.play_position)
                #if self.step_ch1[y][self.play_position] == 1:
            for track in self.current_pattern.tracks:
                if track.tr[track.play_position] == 1:
                    #print("Grid 1:", self.play_position,abs(y-7))
                    #asyncio.async(self.trigger(abs(y-7),0))
                    #change this to add the note at this position on this track into the trigger schedule
                    #ch1_note = abs(y-7) #eventually look up the scale function for this note
                    #print("notes: ", track.note[track.play_position])
                    #print("duration: ", track.duration[track.play_position])
                    #print("octave: ", track.octave[track.play_position])
                    for i in range(len(track.note[track.play_position])):
                    #    print(i,len(track.note[track.play_position]))
                        #self.calc_scale(0) # change this later - should be set in grid_key
                        if track.scale_toggle:
                            current_note = self.cur_scale[track.note[track.play_position][i]-1]+track.octave[track.play_position]*12
                            #print("input note: ", track.note[track.play_position][i], "scaled_note: ", self.cur_scale[track.note[track.play_position][i]-1], "current note: ", current_note)
                        else:
                            #set the note to an increment from some convenient base
                            current_note = track.note[track.play_position][i]+35+track.octave[track.play_position]*12

                        #print("input note: ", track.note[track.playposition[i], "scaled_note: ", current_note)
                        scaled_duration = 0
                        entered_duration = track.duration[track.play_position]
                        if entered_duration == 1:
                            scaled_duration = 1
                        if entered_duration == 2:
                            scaled_duration = 2
                        if entered_duration == 3:
                            scaled_duration =  3
                        if entered_duration == 4:
                            scaled_duration = 4
                        elif entered_duration == 5:
                            scaled_duration = 5
                        elif entered_duration == 6:
                            scaled_duration = 6
                        velocity = track.velocity[track.play_position]*20
                        #print("velocity: ", velocity)
                        #velocity = 65
                        #print("entered: ", entered_duration, "scaled duration: ", scaled_duration)
                        self.insert_note(track.track_id, track.play_position, current_note, velocity, scaled_duration) # hard coding velocity
                        #print("inserted note: ",current_note, velocity,scaled_duration, "on track: ", track.track_id, "at pos: ", track.play_position)

                #if self.cutting:
                    #t.play_position = t.next_position
                    #self.held_keys = 0
                    #print ("cutting to: ", self.next_position[t])
                #elif self.play_position == self.width - 1:
                #    self.play_position = 0
                #elif t.play_position == t.loop_end and t.loop_start != 0:
                #if t.play_position == t.loop_end and t.loop_start != 0:
                    #self.play_position = self.loop_start
                    #print ("looping to: ", self.next_position[t])
                #else:
                #    self.play_position += 1

                self.cutting = False
            #else:
                #buffer = monome.LedBuffer(self.width, self.height)
                #buffer.led_level_set(0, 0, 0)
            #    self.draw()

            asyncio.async(self.trigger())
            #yield from asyncio.sleep(0.1)
            asyncio.async(self.clock_out())
            #yield from self.clock.sync(self.ticks)
            yield from self.clock.sync(self.ticks)
            self.current_pos = yield from self.clock.sync()
            for track in self.current_pattern.tracks:
                track.loop_length = abs(track.loop_end - track.loop_start)+1
                track.play_position = (self.current_pos//self.ticks)%track.loop_length + track.loop_start
            #print("updated play pos: ", self.play_position)
            #self.fine_play_position = self.current_pos%96
            #self.fine_play_position = self.play_position

    def insert_note(self,track,position,pitch,velocity,duration):
        self.insert_note_on(track,position,pitch,velocity)
        #self.insert_note_off(track,(position+duration)%96,pitch)
        self.insert_note_off(track,(position+duration)%16,pitch)
        #print("note off at: ", position, " + ", self.current_pattern.tracks[track].duration[position])

    def insert_note_on(self,track,position,pitch,velocity):
        already_exists = False
        for n in self.note_on[position]:
            if n.pitch == pitch:
                already_exists = True
        if not already_exists:
            new_note = Note(track,pitch,velocity)
            self.note_on[position].append(new_note)

    def insert_note_off(self,track,position,pitch):
        already_exists = False
        for n in self.note_on[position]:
            if n.pitch == pitch:
                already_exists = True
        if not already_exists:
            new_note = Note(track,pitch,0)
            self.note_off[position].append(new_note)

    def calc_scale(self, s):
        self.cur_scale[0] = self.scale_data[s][0] + self.cur_trans
        for i1 in range(1,8):
            self.cur_scale[i1] = self.cur_scale[i1-1] + self.scale_data[s][i1]

# to be removed
    #def gridToSpan(self,x,y):
    #    return [x,y]

    #def spanToGrid(self,x,y):
    #    return [x,y]

#TODO: setup the note data structure and also change the noteon and noteoff structure to be dynamic lists rather than arrays (so we only pick up actual notes, not empties
    @asyncio.coroutine
    def trigger(self):
        #print(self.play_position, self.fine_play_position)
        #notes = list()
        for t in self.current_pattern.tracks:
            for note in self.note_off[t.play_position]:
                #print("position: ", self.fine_play_position, " ending:", note.pitch, " on channel ", self.channel + note.channel_inc)
                #notes.append((self.channel + note.channel_inc,note.pitch+40,0))
                self.midi_out.send_noteon(self.channel + note.channel_inc, note.pitch,0)
            del self.note_off[t.play_position][:] #clear the current midi output once it's been sent

            for note in self.note_on[t.play_position]:
                #print("position: ", self.fine_play_position, " playing:", note.pitch, " on channel ", self.channel + note.channel_inc)
                #notes.append((self.channel + note.channel_inc,note.pitch+40,note.velocity))
                self.midi_out.send_noteon(self.channel + note.channel_inc, note.pitch,note.velocity)
            del self.note_on[t.play_position][:] #clear the current midi output once it's been sent


    @asyncio.coroutine
    def clock_out(self):
        #print("Grid1", i)
        #self.midi_out.note_on(40, 60, self.clock_ch)
        #print("G1: clock on "  + " channel: " + str(self.clock_ch))
        yield from self.clock.sync(self.ticks)
        #yield from asyncio.sleep(0.01)
        #self.midi_out.note_off(40, 0, self.clock_ch)
        #print("G1: clock off "  + " channel: " + str(self.clock_ch))

    def draw(self):
        buffer = monome.LedBuffer(self.width, self.height)

        # display steps
            # highlight the play position - only useful for varibright
            #if x == self.play_position:
            #    highlight = 4
            #else:
            #    highlight = 0

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
                for track in self.current_pattern.tracks:
                    buffer.led_level_set(x, 0+track.track_id, track.tr[x] * 15)
                    # display scale toggle
                    if x < 4:
                        buffer.led_level_set(track.track_id, 5, track.scale_toggle * 15)
                        #print("track: ", track.track_id, "x: ", x, "scale toggle: ", track.scale_toggle)
        elif self.k_mode == Modes.mNote:
            buffer.led_level_set(5,7,0)
            buffer.led_level_set(6,7,15)
            buffer.led_level_set(7,7,0)
            buffer.led_level_set(8,7,0)
            buffer.led_level_set(9,7,0)
            buffer.led_level_set(14,7,0)
            buffer.led_level_set(15,7,0)
            for x in range(self.width):
                #show the triggers for that track on the top row
                #buffer.led_level_set(x, 0, self.current_track.tr[x] * 15)
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
                #show the triggers for that track on the top row
                buffer.led_level_set(x, 0, self.current_track.tr[x] * 15)
                #show the triggers for that track on the top row
                buffer.led_level_set(x, 0, self.current_track.tr[x] * 15)
                #draw the accent toggles - this will move to a velocity page?
                #if self.current_track.velocity[x]:
                #    buffer.led_level_set(x, 0, 15)
                #else:
                #    buffer.led_level_set(x, 0, 0)
                #if self.current_channel == 1:
                    #fill a column top down in the x position
                for i in range (7-self.current_track.velocity[x],7): #ignore bottom row
                    buffer.led_level_set(x, i, 15)
                for i in range (0,7-self.current_track.velocity[x]): #ignore top row
                    buffer.led_level_set(x, i, 0)
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
                buffer.led_level_set(7+self.cur_trans+self.scale_data[self.cur_scale_id][sd],7-sd, 15)
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
            previous_step = [0,0,0,0]
            for track in self.current_pattern.tracks:
                #track 1
                if track.play_position >= track.loop_start and track.play_position <= track.loop_end:
                #if ((self.current_pos//self.ticks)%16) < 16:
                    if buffer.levels[0+track.track_id][track.play_position] == 0:
                        buffer.led_level_set(track.play_position -1, 0+track.track_id, previous_step[track.track_id])
                        buffer.led_level_set(track.play_position, 0+track.track_id, 15)
                        previous_step[track.track_id] = 0
                    else: #toggle an already lit led as we pass over it
                        previous_step[track.track_id] = 15
                        buffer.led_level_set(track.play_position, 0+track.track_id, 0)
                        #buffer.led_level_set(track.play_position, 0+track.track_id, 15)
                else:
                    buffer.led_level_set(self.current_track.play_position, 0+track.track_id, 0)

            #if ((self.current_pos//self.ticks)%16) < 16:
            #    buffer.led_level_set(track.play_position, 0+track.track_id, 15)
            #else:
            #    buffer.led_level_set(self.current_track.play_position, 0, 0)
            ##track 2
            #if ((self.current_pos//self.ticks)%16) < 16:
            #    buffer.led_level_set(self.current_track.play_position, 1, 15)
            #else:
            #    buffer.led_level_set(self.current_track.play_position, 1, 0)
            ##track 3
            #if ((self.current_pos//self.ticks)%16) < 16:
            #    buffer.led_level_set(self.current_track.play_position, 2, 15)
            #else:
            #    buffer.led_level_set(self.current_track.play_position, 2, 0)
            #track 4
            #if ((self.current_pos//self.ticks)%16) < 16:
            #    buffer.led_level_set(self.current_track.play_position, 3, 15)
            #else:
            #    buffer.led_level_set(self.current_track.play_position, 3, 0)
        elif self.k_mode is not Modes.mPattern: # all other modes except pattern
            #display play position of current track
            #if ((self.current_pos//self.ticks)%16) >= self.loop_start and ((self.current_pos//self.ticks)%16) <= self.loop_end:
            if self.current_track.play_position >= self.current_track.loop_start and self.current_track.play_position <= self.current_track.loop_end:
                buffer.led_level_set(self.current_track.play_position, 0, 15)
            else:
                buffer.led_level_set(self.current_track.play_position, 0, 0)

        # update grid
        buffer.render(self)

    def grid_key(self, addr, path, *args):
        x, y, s = self.translate_key(addr,path, *args)
        #self.led_set(x, y, s)
        if s ==1 and y == 0:
            if x == 0:
                #print("Selected Track 1")
                self.current_track = self.current_pattern.tracks[0]
                self.current_track_id = self.current_pattern.tracks[0].track_id
            elif x == 1:
                #print("Selected Track 2")
                self.current_track = self.current_pattern.tracks[1]
                self.current_track_id = self.current_pattern.tracks[1].track_id
            elif x == 2:
                #print("Selected Track 3")
                self.current_track = self.current_pattern.tracks[2]
                self.current_track_id = self.current_pattern.tracks[2].track_id
            elif x == 3:
                #print("Selected Track 4")
                self.current_track = self.current_pattern.tracks[3]
                self.current_track_id = self.current_pattern.tracks[3].track_id
            elif x == 5:
                self.k_mode = Modes.mTr
                #print("Selected:", self.k_mode)
            elif x == 6:
                self.k_mode = Modes.mNote
                #print("Selected:", self.k_mode)
            elif x == 7:
                self.k_mode = Modes.mOct
                #print("Selected:", self.k_mode)
            elif x == 8:
                self.k_mode = Modes.mDur
                #print("Selected:", self.k_mode)
            elif x == 9:
                self.k_mode = Modes.mVel
                #print("Selected:", self.k_mode)
            elif x == 10:
                self.k_mod_mode = ModModes.modLoop
                #print("Selected:", self.k_mod_mode)
            elif x == 11:
                self.k_mod_mode = ModModes.modTime
                #print("Selected:", self.k_mod_mode)
            elif x == 12:
                self.k_mod_mode = ModModes.modProb
                #print("Selected:", self.k_mod_mode)
            elif x == 14:
                self.k_mode = Modes.mScale
                #print("Selected:", self.k_mode)
            elif x == 15:
                self.k_mode = Modes.mPattern
                #print("Selected:", self.k_mode)
        elif s == 1 and y > 0:
            if y < 7:
                #set scale mode toggles
                if self.k_mode == Modes.mTr:
                    #print("Trigger page key:", x, y)
                    if y == 2 and x < 4:
                        self.current_pattern.tracks[x].scale_toggle ^= 1
                        #print ("toggling scale for track: ", x)
                # Note entry
                if self.k_mode == Modes.mNote:
                    if self.current_track.track_id == 0:
                        self.current_pattern.step_ch1[7-y][x] ^= 1
                    elif self.current_track.track_id == 1:
                        self.current_pattern.step_ch2[7-y][x] ^= 1
                    elif self.current_track.track_id == 2:
                        self.current_pattern.step_ch3[7-y][x] ^= 1
                    else:
                        self.current_pattern.step_ch4[7-y][x] ^= 1
                    if y not in self.current_track.note[x]:
                        self.current_track.note[x].append(y)
                        #print("append: ", y, "at ", x)
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
                    self.draw()
                # octave entry
                if self.k_mode == Modes.mOct: 
                    #if self.current_channel == 1:
                    if y < 7 and y > 0:
                        self.current_track.octave[x] = y-3
                        #print("grid_key = ", y, "octave = ", self.current_pattern.tracks[0].octave[x])
                    #else:
                    #    if y < 6 and y > 0:
                    #        self.current_pattern.tracks[1].octave[x] = y-3
                    self.draw()
                # duration entry
                if self.k_mode == Modes.mDur:
                    #if self.current_channel == 1:
                    if y == 7:
                        #add accent toggles on top row
                        #self.current_track.accent[x] ^= 1
                        print("accent shifting to velocity soon")
                    else:
                        #enter duration
                        self.current_track.duration[x] = 7-y
                    #else:
                    #    self.current_pattern.tracks[1].duration[x] = 7-y
                    self.draw()
                if self.k_mode == Modes.mVel:
                    #if self.current_channel == 1:
                    self.current_track.velocity[x] = y
                    #print("entered velocity: ", self.current_track.velocity[x])
                    #else:
                    #    self.current_pattern.tracks[1].duration[x] = 7-y
                    self.draw()
                if self.k_mode == Modes.mScale:
                    #if self.current_channel == 1:
                    if x < 3:
                        if y < 7 and y > 0:
                            self.cur_scale_id = y-1+x*6
                            self.calc_scale(self.cur_scale_id)
                            #print("selected scale: ", self.cur_scale_id)
                    else:
                        # transpose the scale up or down by semitones from the mid point (col 7)
                        self.cur_trans = x-7
                        self.calc_scale(self.cur_scale_id)
                    #else:
                    #    self.current_pattern.tracks[1].duration[x] = 7-y
                    self.draw()
                # preset entry
                if self.k_mode == Modes.mPattern:
                    if x < 3:
                        if y < 6 and y > 0:
                            self.state.current_preset_id = y-1+x*5
                            self.current_preset = self.state.presets[self.state.current_preset_id]
                            #print("selected preset: ", self.state.current_preset_id)
                    self.draw()
            # cut and loop
            elif self.k_mode == Modes.mPattern and y == 7:
                self.current_preset.current_pattern = x
                self.current_pattern = self.current_preset.patterns[self.current_preset.current_pattern]
                self.current_track = self.current_pattern.tracks[self.current_track_id]
               # print("selected pattern: ", self.current_preset.current_pattern)
            elif y == 7:
                self.keys_held = self.keys_held + (s * 2) - 1
                #print("keys_held: ", self.keys_held)
                # cut
                if s == 1 and self.keys_held == 1:
                    self.cutting = True
                    self.current_track.next_position = x
                    self.current_track.key_last = x
                    #print("key_last: ", self.key_last[self.current_track])
                # set loop points
                elif s == 1 and self.keys_held == 2:
                    if self.current_track.key_last < x: # don't wrap around, for now
                        self.current_track.loop_start = self.current_track.key_last
                        self.current_track.loop_end = x
                        self.keys_held = 0
                    else:
                        self.keys_held = 0
                    #print("loop start: ", self.loop_start[self.current_track], "end: ", self.loop_end[self.current_track])

    def restore_state(self):
        #load the pickled AST for this feature
        self.state = pickle.load(open(pickle_file_path, "rb"))

    def save_state(self):
        with open(self.pickle_file_path, 'wb') as pickle_handle:
            pickle.dump(self.state, pickle_handle)



class Test1(monome.Monome):
    def __init__(self):
        super().__init__('/hello')

    def ready(self):
        self.x_offset=0

    def gridToSpan(self,x,y):
        return [x,y]
        #return [abs(y-7),x]
    #    return [abs(x-7),abs(y-7)]

    def spanToGrid(self,x,y):
        return [x,y]
        #return [y,abs(x-7)]
    #    return [abs(x-7),abs(y-7)]

    # replace with VirtualGrid code??
    def grid_key(self, x, y, s):
        self.led_set(x, y, s)
    #    span_coord = self.gridToSpan(x,y)
    #    print("grid 1: ", x,y, span_coord, self.spanToGrid(span_coord[0],span_coord[1]))

class Test2(monome.Monome):
    def __init__(self):
        super().__init__('/hello')

    def ready(self):
        self.x_offset=8

    def gridToSpan(self,x,y):
        return [abs(y+self.x_offset),abs(x-7)]

    def spanToGrid(self,x,y):
        return [abs(y-7),abs(x-self.x_offset)]

    def grid_key(self, x, y, s):
        self.led_set(x, y, s)
        span_coord = self.gridToSpan(x,y)
        print("grid 2: ", x,y, span_coord, self.spanToGrid(span_coord[0],span_coord[1]))

class Test3(spanned_monome.VirtualGrid):
    def __init__(self):
        super().__init__('runcible') #maybe just setting the name of the virtual grid here allows the size to be looked up?

    def ready(self):
        self.x_offset=0

    #def grid_key(self, x, y, s):
    #    x, y, s = self.translate_key(x, y, s)
    #    self.led_set(x, y, s)
        #print("runcible: ", x,y)

    def grid_key(self, addr, path, *args):
        x, y, s = self.translate_key(addr,path, *args)
        data1 = [[1,1,1,1,1,1,1,1],
                [0,0,0,0,0,0,0,0],
                [1,1,1,1,1,1,1,1],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0]]

        data2 = [[0,0,0,0,0,0,0,0],
                [1,1,1,1,1,1,1,1],
                [0,0,0,0,0,0,0,0],
                [1,1,1,1,1,1,1,1],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0]]

        clear_all = [[0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0]]
        if x == 0 and y == 0:
            self.led_map(0,0,data1)
            self.led_map(8,0,data2)
        else:
            self.led_map(0,0,clear_all)
            self.led_map(8,0,clear_all)
            self.led_set(x, y, s)

class Test4(spanned_monome.VirtualGrid):
    def __init__(self):
        super().__init__('/hello')
        aiosc(('127.0.0.1', 9000), '/hello', 'world')

if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    #pygame.init()
    #pygame.midi.init()
    #device_count = pygame.midi.get_count()
    #print (pygame.midi.get_default_output_id())
    #midiport = 0
    #clock_out = 3
    #info = list()
    #for i in range(device_count):
    #   info = pygame.midi.get_device_info(i)
    #   print (str(i) + ": " + str(info[1]) + " " + str(info[2]) + " " + str(info[3]))
    #   if 'MIDI 6' in str(info[1]) and info[3] == 1:
    #       midiport = i
       #if 'MIDI 1' in str(info[1]) and info[3] == 0:
       #   clock_out = i

    #midi_out = pygame.midi.Output(midiport, 0)

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
    #page = 1
    #midi_out=None

    # create clock
    #coro = loop.create_datagram_endpoint(clocks.FooClock, local_addr=('127.0.0.1', 9000))
    #transport, clock = loop.run_until_complete(coro)
    #clock = clocks.InaccurateTempoClock(120)
    #g1 = lambda: GridSeq1(clock,24,midi_out,channel_out,clock_out,page)
    #g2 = lambda: GridSeq2(clock,24,midi_out,channel_out,clock_out,page)

    clock = clocks.RtMidiClock()
    #g1 = lambda: None
    #g2 = lambda: GridSeq2(clock,6,midi_out,channel_out,clock_out,g1)
    g1 = lambda: Runcible(clock,6,midi_out,channel_out,clock_out,None)
#    r1 = lambda: Test1()
#    r2 = lambda: Test2()
    sg1 = lambda: Test3()
    sg2 = lambda: GridStudies()

    #g1 = lambda: Test1()
    #g2 = lambda: Test2()
    #coro = monome.create_serialosc_connection({
    #      'm40h-001': g1,
    #      'm40h-002': g2,
    #}, loop=loop)

    #coro, g1_coro  = monome.create_spanned_serialosc_connection({
    coro = spanned_monome.create_spanned_serialosc_connection({
          'runcible': g1,
    }, loop=loop)

    # create synth
#    coro = loop.create_datagram_endpoint(synths.Renoise, local_addr=('127.0.0.1', 0), remote_addr=('127.0.0.1', 8001))
#    transport, renoise = loop.run_until_complete(coro)

#    coro = monome.create_serialosc_connection(lambda: Flin(clock, renoise, 0))
    #g1_serialosc = loop.run_until_complete(g1_coro)
    serialosc = loop.run_until_complete(coro)

    try: # can we all methods in the app which handle page setting updates? If so, then we just need something which returns a value to the main without breaking the loop
        loop.run_forever()
    except KeyboardInterrupt:
        for apps in serialosc.app_instances.values():
            for app in apps:
                app.disconnect()
        midi_out.close_port()
        print('kthxbye')

