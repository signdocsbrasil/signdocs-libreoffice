# SPDX-License-Identifier: MPL-2.0
"""UNO dialog layer.

Everything in this package touches the office UI and must therefore run on the
main thread. Network work belongs in a worker thread with results marshalled
back through com.sun.star.awt.AsyncCallback — calling into here from a worker
freezes the whole suite.
"""
