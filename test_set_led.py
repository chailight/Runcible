#! /usr/bin/env python3

import asyncio
import aiosc

loop = asyncio.get_event_loop()
loop.run_until_complete(
    #aiosc.send(('127.0.0.1', 8001), '/m40h-002/grid/led/set', 0, 0, 1)
    #sleep(10)
    aiosc.send(('127.0.0.1', 8001), '/m40h-002/grid/led/set', 0, 0, 0)
)
