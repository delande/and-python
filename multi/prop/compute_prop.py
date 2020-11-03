#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
# compute_prop.py
# Author: Dominique Delande
# Release date: April, 27, 2020
# License: GPL2 or later
"""
Created on Fri Aug 16 17:05:10 2019

@author: delande

Disordered system in any dimension
Discretization in configuration space
3-point discretization of the Laplace operator along each direction

This program computes the temporal propagation of any initial state

V0 (=disorder_strength) is the square root of the variance of the disorder
sigma (=correlation_length) is the correlation length of the disorder
Various disorder types can be used, defined by the disorder_type variable:
  anderson gaussian: Usual Anderson model (spatially uncorrelated disorder) with Gaussian on-site distribution of the disorder
  regensburg: Gaussian on-site distribution with spatial correlation function <V(r)V(r+delta)>=V_0^2 exp(-0.5*delta^2/sigma^2)
  singapore: Gaussian on-site distribution with spatial correlation function <V(r)V(r+delta)>=V_0^2 sinc(delta/sigma)
  konstanz: Rayleigh on-site distribution (average V_0, variance V_0^2) with spatial correlation function <V(r)V(r+delta)>=V_0^2 exp(-0.5*delta^2/sigma^2)
  speckle: Rayleigh on-site distribution (average V_0, variance V_0^2) with spatial correlation function <V(r)V(r+delta)>=V_0^2 (1+sinc^2(delta/sigma))

  Internally, the wavefunction can be stored using two different layouts.
  This does NOT affect the storage of the wavefunctions used for measurements, which is always 'complex'
  This affecty only the vector used in the guts of the propagation algorithm.
  'real' is usually a bit faster.
  For data_layout == 'complex':
        wfc is assumed to be in format where
        wfc[0:2*dim_x:2] contains the real part of the wavefunction and
        wfc[1:2*dim_x:2] contains the imag part of the wavefunction.
      For data_layout == 'real':
        wfc is assumed to be in format where
        wfc[0:dim_x] contains the real part of the wavefunction and
        wfc[dim_x:2*dim_x] contains the imag part of the wavefunction.

"""

import os
import time
import math
import numpy as np
import getpass
import copy
import configparser
import sys
import socket
import argparse
#sys.path.append('../')
sys.path.append('/users/champ/delande/git/and-python/multi')
import anderson



def main():
  parser = argparse.ArgumentParser(description='Compute temporal propagation using the Gross-Pitaevskii or Schoedinger equation')
  parser.add_argument('filename', type=argparse.FileType('r'), help='name of the file containing parameters of the calculation')
  args = parser.parse_args()
  parameter_file = args.filename.name

# Determine is the script is ran inside MPI
# If yes, set the mpi_version to True, the  MPI communicator to comm, the number of
# MPI processes to nprocs, the rank of the current process to rank, and
# set mpi_string to something containing minimal MPI information
# If not run inside MPI, nprocs=1 and rank=0
  mpi_version, comm, nprocs, rank, mpi_string = anderson.determine_if_launched_by_mpi()
  environment_string='Script ran by '+getpass.getuser()+' on machine '+socket.getfqdn()+'\n'\
             +'Name of python script:  {}'.format(os.path.abspath( __file__ ))+'\n'\
             +'Name of parameter file: {}'.format(os.path.abspath(parameter_file))+'\n'\
             +mpi_string+'\n'

  if rank==0:
    initial_time=time.asctime()
#    hostname = os.uname()[1].split('.')[0]
    print("Python script runs on machine : "+socket.getfqdn())
    print("Name of python script:  {}".format(os.path.abspath( __file__ )))
    print("Name of parameter file: {}".format(os.path.abspath(parameter_file)))
    print()
    print("Python script started on: {}".format(initial_time))
    print()

# Parse parameter file and prepare the useful objects:
# H for the Hamiltonian of the system
# initial_state for the initial state
# propagation for the propagation scheme
# measurement for the measurement scheme
# measurement_global is used to gather (average) the results for several disorder configurations
# my_list_of_sections is the list of sections needed for this particular calculation
# Can be in any order
# The list determines the various structures returned by the routine
# Must be consistent otherwise disaster guaranted
  my_list_of_sections = ['Wavefunction','Nonlinearity','Propagation','Measurement']
  H, initial_state, propagation, measurement, measurement_global, n_config = anderson.io.parse_parameter_file(mpi_version,comm,nprocs,rank,parameter_file,my_list_of_sections)

  t1=time.perf_counter()
  timing=anderson.Timing()
# The following line is a temporary fix
  i_tab_0 = 0

  if rank==0:

# Print various things for the initial state
# At this point, it it not yet known whether there is a C implementation available
    header_string = environment_string+anderson.io.output_string(H,n_config,nprocs,initial_state=initial_state,propagation=propagation,measurement=measurement_global)
#  print(header_string)
# Print the initial density in configuration space
    if measurement_global.measure_density:
      anderson.io.output_density('density_initial.dat',np.abs(initial_state.wfc)**2,H,tab_abscissa=initial_state.tab_position,header_string=header_string,data_type='density',file_type='savetxt')
# Print the initial density in momentum space
    if (measurement_global.measure_density_momentum):
      anderson.io.output_density('density_momentum_initial.dat',np.abs(initial_state.convert_to_momentum_space())**2,H,tab_abscissa=measurement.frequencies,header_string=header_string,data_type='density_momentum',file_type='savetxt')
# The initial wavefunction in configuration space
    if (measurement_global.measure_wavefunction):
      anderson.io.output_density('wavefunction_initial.dat',initial_state.wfc,H,header_string=header_string,tab_abscissa=initial_state.tab_position,data_type='wavefunction')
# The initial wavefunction in momentum space
    if (measurement_global.measure_wavefunction_momentum):
      anderson.io.output_density('wavefunction_momentum_initial.dat',initial_state.convert_to_momentum_space(),H,header_string=header_string,tab_abscissa=measurement.frequencies,data_type='wavefunction_momentum')

# Next line useful only if one wants to compute the potential correlation function
# pot_correl=np.zeros(H.tab_dim)

# Here starts the loop over disorder configurations
  for i in range(n_config):
# Propagation for one realization of disorder
    anderson.propagation.gpe_evolution(i+rank*n_config, initial_state, H, propagation, measurement, timing)
# Add the current contribution to the sum of previous ones
    measurement_global.merge_measurement(measurement)
# The following lines just for generating and printing a single realization of disorder
#   H.generate_disorder(i+rank*n_config+1234)
#   print(H.disorder)
#   np.savetxt('potential.dat',H.disorder-H.diagonal)
# The following lines for computing the potential correlation function
#   pot_correl += np.real(anderson.compute_correlation(H.disorder-H.diagonal,H.disorder-H.diagonal))
# pot_correl /= n_config
# np.savetxt('potential_correlation.dat',np.fft.fftshift(pot_correl))

# Merge measured quantities in the various MPI processes
  if mpi_version:
    measurement_global.mpi_merge_measurement(comm,timing)

# Calculation is essentially finished
# It remains to output the results
  t2 = time.perf_counter()
  timing.TOTAL_TIME = t2-t1
  if mpi_version:
    timing.mpi_merge(comm)

  if rank==0:
# After the calculation, whether the C implementation has been used is known, hence recompute the header string
    environment_string+='Calculation   ended on: {}'.format(time.asctime())+'\n\n'
    header_string = environment_string+anderson.io.output_string(H,n_config,nprocs,initial_state=initial_state,propagation=propagation,measurement=measurement_global,timing=timing)
#    print('header',header_string)
    tab_strings, tab_dispersion = measurement_global.normalize(n_config*nprocs)
    if (measurement_global.measure_density):
      anderson.io.output_density('density_final.dat',measurement_global.density_final,H,header_string=header_string,tab_abscissa=initial_state.tab_position,data_type='density')
    if (measurement_global.measure_density_momentum):
      anderson.io.output_density('density_momentum_final.dat',measurement_global.density_momentum_final,H,header_string=header_string,tab_abscissa=measurement.frequencies,data_type='density_momentum')
    if (measurement_global.measure_wavefunction):
      anderson.io.output_density('wavefunction_final.dat',measurement_global.wfc,H,header_string=header_string,tab_abscissa=initial_state.tab_position,data_type='wavefunction')
    if (measurement_global.measure_wavefunction_momentum):
      anderson.io.output_density('wavefunction_momentum_final.dat',measurement_global.wfc_momentum,H,header_string=header_string,tab_abscissa=measurement.frequencies,data_type='wavefunction_momentum')
    if (measurement_global.measure_autocorrelation):
      anderson.io.output_density('temporal_autocorrelation.dat',measurement_global.tab_autocorrelation,H,tab_abscissa=measurement.tab_t_measurement[i_tab_0:]-measurement.tab_t_measurement[i_tab_0],header_string=header_string,data_type='autocorrelation')
    if (measurement_global.measure_dispersion_position or measurement_global.measure_dispersion_momentum or measurement_global.measure_dispersion_energy):
      anderson.io.output_dispersion('dispersion.dat',tab_dispersion,tab_strings,header_string)
    if (measurement_global.measure_g1):
      anderson.io.output_density('g1_final.dat',measurement_global.g1,H,header_string=header_string,tab_abscissa=initial_state.tab_position,data_type='g1')
#    if (measurement_global.measure_overlap):
#      print("Squared overlap with initial state = ",abs(measurement_global.overlap)**2)

    """
  i_tab_0 = propagation.first_measurement_autocorr

  header_string=environment_string\
             +params_string\
             +'Temporal autocorrelation function\n'\
             +'Column 1: Time\n'\
             +'Column 2: Real(<psi(0)|psi(t)>)\n'\
             +'Column 3: Imag(<psi(0)|psi(t)>)\n'\
             +'\n'
  np.savetxt('temporal_autocorrelation.dat',np.column_stack([propagation.tab_t_measurement[i_tab_0:]-propagation.tab_t_measurement[i_tab_0],np.mean(np.real(tab_autocorrelation[:,:number_of_measurements-i_tab_0]),0),np.mean(np.imag(tab_autocorrelation[:,:number_of_measurements-i_tab_0]),0)]),header=header_string)
    """

    final_time = time.asctime()
    print("Python script ended on: {}".format(final_time))
    print("Wallclock time {0:.3f} seconds".format(t2-t1))
    print()
    if (propagation.method=='ode'):
      print("GPE time             = {0:.3f}".format(timing.GPE_TIME))
      print("Number of time steps =",timing.N_SOLOUT)
    else:
      print("CHE time             = {0:.3f}".format(timing.CHE_TIME))
      print("Max nonlinear phase  = {0:.3f}".format(timing.MAX_NONLINEAR_PHASE))
      print("Max order            =",timing.MAX_CHE_ORDER)
    print("Expect time          = {0:.3f}".format(timing.EXPECT_TIME))
    if mpi_version:
      print("MPI time             = {0:.3f}".format(timing.MPI_TIME))
    print("Dummy time           = {0:.3f}".format(timing.DUMMY_TIME))
    print("Number of ops        = {0:.4e}".format(timing.NUMBER_OF_OPS))
    print("Total_CPU time       = {0:.3f}".format(timing.TOTAL_TIME))

if __name__ == "__main__":
  main()


