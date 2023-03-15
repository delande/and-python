#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Aug 16 17:05:10 2019

@author: delande

"""
__author__ = "Dominique Delande"
__copyright__ = "Copyright (C) 2020 Dominique Delande"
__license__ = "GPL version 2 or later"
__version__ = "1.0"
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>.
# ____________________________________________________________________
#
# compute_IPR.py
# Author: Dominique Delande
# Release date: April, 27, 2020
# License: GPL2 or later

import os
import time
import numpy as np
import getpass
import timeit
import sys
import argparse
sys.path.append('/users/champ/delande/git/and-python')
sys.path.append('/home/lkb/delande/git/and-python')
import anderson


def main():
  parser = argparse.ArgumentParser(description='Compute the eigenstate closest to some target energy')
  parser.add_argument('filename', type=argparse.FileType('r'), help='name of the file containing parameters of the calculation')
  args = parser.parse_args()
  parameter_file = args.filename.name

# Determine is the script is ran inside MPI
# If yes, set the mpi_version to True, the  MPI communicator to comm, the number of
# MPI processes to nprocs, the rank of the current process to rank, and
# set mpi_string to something containing minimal MPI information
# If not run inside MPI, nprocs=1 and rank=0
  mpi_version, comm, nprocs, rank, mpi_string = anderson.determine_if_launched_by_mpi()
  environment_string='Script ran by '+getpass.getuser()+' on machine '+os.uname()[1]+'\n'\
             +'Name of python script:  {}'.format(os.path.abspath( __file__ ))+'\n'\
             +'Name of parameter file: {}'.format(os.path.abspath(parameter_file))+'\n'\
             +mpi_string+'\n'

  if rank==0:
    initial_time=time.asctime()
#    hostname = os.uname()[1].split('.')[0]
    print("Python script runs on machine : "+os.uname()[1])
    print("Name of python script:  {}".format(os.path.abspath( __file__ )))
    print("Name of parameter file: {}".format(os.path.abspath(parameter_file)))
    print()
    print("Python script started on: {}".format(initial_time))
    print()

# Parse parameter file and prepare the useful objects:
# H for the Hamiltonian of the system
# diagonalization for exact (or sparse) diagonalization
  geometry, H, _, diagonalization, n_config = anderson.io.parse_parameter_file(mpi_version,comm,nprocs,rank,parameter_file,['Diagonalization','Spin'])

  t1=time.perf_counter()
  my_timing=anderson.timing.Timing()

  if rank==0:

# Print various things for the initial state
# At this point, it it not yet known whether there is a C implementation available
    header_string = environment_string+anderson.io.output_string(H,n_config,nprocs,diagonalization=diagonalization)

#  number_of_eigenvalues = diagonalization.number_of_eigenvalues
#  print(H.tab_dim)
#  print(tab_eigenstate)
  # Here starts the loop over disorder configurations
  for i in range(n_config):
#    tab_energy[i*number_of_eigenvalues:(i+1)*number_of_eigenvalues], tab_eigenstate[:,i*number_of_eigenvalues:(i+1)*number_of_eigenvalues] = diagonalization.compute_wavefunction(i+rank*n_config, H)
    a, b = diagonalization.compute_wavefunction(i+rank*n_config, H)
    energy = a[0]
    tab_eigenstate = b[:,0].reshape(H.tab_dim)
#    print(energy,tab_eigenstate)
  t2 = time.perf_counter()
  my_timing.TOTAL_TIME = t2-t1
  if rank==0:
    header_string +='Energy = '+str(energy)+'\n'
    anderson.io.output_density('density.dat',tab_eigenstate**2,H,header_string=header_string,data_type='density')
    final_time = time.asctime()
    print("Python script ended on: {}".format(final_time))
    print("Wallclock time {0:.3f} seconds".format(t2-t1))
    print()
    if mpi_version:
      print("MPI time             = {0:.3f}".format(my_timing.MPI_TIME))
    print("Total_CPU time       = {0:.3f}".format(my_timing.TOTAL_TIME))

if __name__ == "__main__":
  main()
