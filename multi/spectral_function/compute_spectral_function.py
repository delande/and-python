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
# compute_spectral_function.py
# Author: Dominique Delande
# Release date: April, 27, 2020
# License: GPL2 or later
"""
Created on Fri Aug 16 17:05:10 2019

@author: delande

Disordered many-dimensional system
Discretization in configuration space
3-point discretization of the Laplace operator (in each direction)

This program computes the spectral function (using Fourier transform of the temporal propagation)

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
        wfc[0:2*ntot:2] contains the real part of the wavefunction and
        wfc[1:2*ntot:2] contains the imag part of the wavefunction.
      For data_layout == 'real':
        wfc is assumed to be in format where
        wfc[0:ntot] contains the real part of the wavefunction and
        wfc[ntot:2*ntot] contains the imag part of the wavefunction.

"""

import os
import time
import math
import numpy as np
import getpass
import copy
import configparser
import sys
sys.path.append('../')
sys.path.append('/users/champ/delande/git/and-python/multi')
import anderson

if __name__ == "__main__":
  environment_string='Script ran by '+getpass.getuser()+' on machine '+os.uname()[1]+'\n'\
             +'Name of python script: {}'.format(os.path.abspath( __file__ ))+'\n'\
             +'Started on: {}'.format(time.asctime())+'\n'
  try:
# First try to detect if the python script is launched by mpiexec/mpirun
# It can be done by looking at an environment variable
# Unfortunaltely, this variable depends on the MPI implementation
# For MPICH and IntelMPI, MPI_LOCALNRANKS can be checked for existence
#   os.environ['MPI_LOCALNRANKS']
# For OpenMPI, it is OMPI_COMM_WORLD_SIZE
#   os.environ['OMPI_COMM_WORLD_SIZE']
# In any case, when importing the module mpi4py, the MPI implementation for which
# the module was created is unknown. Thus, no portable way...
# The following line is for OpenMPI
    os.environ['OMPI_COMM_WORLD_SIZE']
# If no KeyError raised, the script has been launched by MPI,
# I must thus import the mpi4py module
    from mpi4py import MPI
    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    nprocs = comm.Get_size()
    mpi_version = True
    environment_string += 'MPI version ran on '+str(nprocs)+' processes\n\n'
  except KeyError:
# Not launched by MPI, use sequential code
    mpi_version = False
    nprocs = 1
    rank = 0
    environment_string += 'Single processor version\n\n'
  except ImportError:
# Launched by MPI, but no mpi4py module available. Abort the calculation.
    exit('mpi4py module not available! I stop!')

  if rank==0:
    initial_time=time.asctime()
    hostname = os.uname()[1].split('.')[0]
    print("Python script started on: {}".format(initial_time))
    print("{:>24}: {}".format('from',hostname))
    print("Name of python script: {}".format(os.path.abspath( __file__ )))

    config = configparser.ConfigParser()
    config.read('params.dat')

    Averaging = config['Averaging']
    n_config = Averaging.getint('n_config',1)
    n_config = (n_config+nprocs-1)//nprocs
    print("Total number of disorder realizations: {}".format(n_config*nprocs))
    print("Number of processes: {}".format(nprocs))

    System = config['System']
    dimension = System.getint('dimension', 1)
    tab_size = list()
    tab_delta = list()
    tab_boundary_condition = list()
    for i in range(dimension):
      tab_size.append(System.getfloat('size_'+str(i+1)))
      tab_delta.append(System.getfloat('delta_'+str(i+1)))
      tab_boundary_condition.append(System.get('boundary_condition_'+str(i+1),'periodic'))
#    print(dimension,tab_size,tab_delta,tab_boundary_condition)

    Disorder = config['Disorder']
    disorder_type = Disorder.get('type','anderson gaussian')
    correlation_length = Disorder.getfloat('sigma',0.0)
    V0 = Disorder.getfloat('V0',0.0)
    disorder_strength = V0
    use_mkl_random = Disorder.getboolean('use_mkl_random',True)

    Nonlinearity = config['Nonlinearity']
    interaction_strength = Nonlinearity.getfloat('g',0.0)

    Wavefunction = config['Wavefunction']
    initial_state_type = Wavefunction.get('initial_state')
    tab_k_0 = list()
    tab_sigma_0 = list()
    for i in range(dimension):
      tab_k_0.append(2.0*math.pi*Wavefunction.getfloat('k_0_over_2_pi_'+str(i+1)))
      tab_sigma_0.append(Wavefunction.getfloat('sigma_0_'+str(i+1)))

    Propagation = config['Propagation']
    method = Propagation.get('method','che')
    data_layout = Propagation.get('data_layout','real')
    i_tab_0 = 0

    Spectral = config['Spectral']
    e_range = Spectral.getfloat('range')
    e_resolution = Spectral.getfloat('resolution')

    Measurement = config['Measurement']
    use_mkl_fft = Measurement.getboolean('use_mkl_fft',True)
  else:
    dimension = None
    n_config = None
    tab_size = None
    tab_delta = None
    tab_boundary_condition = None
    disorder_type = None
    correlation_length = None
    disorder_strength = None
    use_mkl_random = None
    interaction_strength = None
    initial_state_type = None
    tab_k_0 = None
    tab_sigma_0 = None
    method = None
    data_layout = None
    t_max = None
    delta_t = None
    i_tab_0 = None
    e_range = None
    e_resolution = None
    use_mkl_fft = None

  if mpi_version:
    n_config, dimension,tab_size,tab_delta,tab_boundary_condition  = comm.bcast((n_config,dimension,tab_size,tab_delta,tab_boundary_condition))
    disorder_type, correlation_length, disorder_strength, use_mkl_random, interaction_strength = comm.bcast((disorder_type, correlation_length, disorder_strength, use_mkl_random, interaction_strength))
    initial_state_type, tab_k_0, tab_sigma_0 = comm.bcast((initial_state_type, tab_k_0, tab_sigma_0))
    method, data_layout, i_tab_0, e_range, e_resolution, use_mkl_fft = comm.bcast((method, data_layout,  i_tab_0, e_range, e_resolution, use_mkl_fft))


  t1=time.perf_counter()
  timing=anderson.Timing()

# Number of sites
  tab_dim = list()
  for i in range(dimension):
    tab_dim.append(int(tab_size[i]/tab_delta[i]+0.5))
# Renormalize delta so that the system size is exactly what is wanted and split in an integer number of sites
    tab_delta[i] = tab_size[i]/tab_dim[i]
#  print(tab_dim)

  try:
    import mkl
    mkl.set_num_threads(1)
    os.environ["MKL_NUM_THREADS"] = "1"
  except:
    pass

  spectral_function = anderson.propagation.Spectral_function(e_range,e_resolution)

  for i in range(dimension):
    assert tab_boundary_condition[i] in ['periodic','open'], "Boundary condition must be either 'periodic' or 'open'"

# Prepare Hamiltonian structure (the disorder is NOT computed, as it is specific to each realization)
  H = anderson.Hamiltonian(dimension,tab_dim,tab_delta, tab_boundary_condition=tab_boundary_condition, disorder_type=disorder_type, correlation_length=correlation_length, disorder_strength=disorder_strength, use_mkl_random=use_mkl_random, interaction=interaction_strength)
# Define an initial state
  initial_state = anderson.Wavefunction(tab_dim,tab_delta)
  initial_state.type = initial_state_type
  assert initial_state.type in ["plane_wave","gaussian_wave_packet"], "Initial state is not properly defined"
  if (initial_state.type=='plane_wave'):
    anderson.Wavefunction.plane_wave(initial_state,tab_k_0)
  if (initial_state.type=='gaussian_wave_packet'):
    anderson.Wavefunction.gaussian(initial_state,tab_k_0,tab_sigma_0)
#  np.savetxt('wfc.dat',initial_state.wfc)
#  print(initial_state.overlap(initial_state))

# Define the structure of the temporal integration
  propagation = anderson.propagation.Temporal_Propagation(spectral_function.t_max,spectral_function.delta_t,method=method,data_layout=data_layout)

  measurement = anderson.propagation.Measurement(spectral_function.delta_t,  measure_autocorrelation=True, use_mkl_fft=use_mkl_fft)
  measurement_global = copy.deepcopy(measurement)
  measurement.prepare_measurement(propagation,tab_delta,tab_dim)
#  print(measurement.density_final.shape)
  measurement_global.prepare_measurement_global(propagation,tab_delta,tab_dim)
  header_string = environment_string+anderson.io.output_string(H,n_config,nprocs,initial_state=initial_state,propagation=propagation,measurement=measurement_global,spectral_function=spectral_function)

#  print(header_string)

# Here starts the loop over disorder configurations
  for i in range(n_config):
    anderson.propagation.gpe_evolution(i+rank*n_config, initial_state, H, propagation, measurement, timing)
    measurement_global.merge_measurement(measurement)
#  print(measurement_global.tab_position)
#
  if mpi_version:
    measurement_global.mpi_merge_measurement(comm,timing)
  t2 = time.perf_counter()
  timing.TOTAL_TIME = t2-t1
  if mpi_version:
    timing.mpi_merge(comm)
#    print('Before: ',rank,measurement_global.tab_autocorrelation[-1])
#    toto = np.empty_like(measurement_global.tab_autocorrelation)
#    comm.Reduce(measurement_global.tab_autocorrelation,toto,op=MPI.SUM)
#    measurement_global.tab_autocorrelation = toto
#    timing.CHE_TIME = comm.reduce(timing.CHE_TIME)
#    global_timing=comm.reduce(timing)
#    print(rank,global_timing.CHE_TIME)
#    print('After: ',rank,measurement_global.tab_autocorrelation[-1])
  if rank==0:
    tab_strings, tab_dispersion = measurement_global.normalize(n_config*nprocs)
    anderson.io.output_density('temporal_autocorrelation.dat', measurement_global.tab_autocorrelation, tab_abscissa=measurement_global.tab_t_measurement[i_tab_0:]-measurement_global.tab_t_measurement[i_tab_0], header_string=header_string,data_type='autocorrelation')
    tab_energies,tab_spectrum = spectral_function.compute_spectral_function(measurement_global.tab_autocorrelation)
    anderson.io.output_density('spectral_function.dat',tab_spectrum,tab_abscissa=tab_energies,header_string=header_string,data_type='spectral_function')

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

