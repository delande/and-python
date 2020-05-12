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
import math
import numpy as np
import getpass
import configparser
import timeit
import sys
#sys.path.append('../')
sys.path.append('/users/champ/delande/git/and-python/')
import anderson
import mkl

def compute_wigner_function(H,tab_wfc):
  number_of_eigenvalues = tab_wfc.shape[1]
  dim_x = tab_wfc.shape[0]
  tab_wigner = np.zeros((dim_x//2,dim_x,number_of_eigenvalues))
  tab_intermediate1 = np.zeros(dim_x,dtype=np.complex128)
  tab_intermediate2 = np.zeros(dim_x,dtype=np.complex128)
#  np.savetxt('orig_x.dat',np.column_stack((np.real(tab_wfc[:,0]),np.imag(tab_wfc[:,0]))))
  for i in range(number_of_eigenvalues):
    for j in range(dim_x):
      tab_intermediate1[0:dim_x-j]=tab_wfc[j:dim_x,i]
      tab_intermediate1[dim_x-j:dim_x]=tab_wfc[0:j,i]
      tab_intermediate2[0:j+1]=tab_wfc[j::-1,i]
      tab_intermediate2[j+1:dim_x]=tab_wfc[:j:-1,i]
#     tab_wigner[:,j,i] = np.real(np.fft.fft(tab_intermediate1*np.conj(tab_intermediate2)))
#      if j==50:
#        np.savetxt('orig_x1.dat',np.column_stack((np.real(tab_intermediate1),np.imag(tab_intermediate1))))
#        np.savetxt('orig_x2.dat',np.column_stack((np.real(tab_intermediate2),np.imag(tab_intermediate2))))
#        np.savetxt('znort_x.dat',np.column_stack((np.real(tab_intermediate1*np.conj(tab_intermediate2)),np.imag(tab_intermediate1*np.conj(tab_intermediate2)))))
#        np.savetxt('znort_p.dat',np.column_stack((np.real(np.fft.fft(tab_intermediate1*np.conj(tab_intermediate2))),np.imag(np.fft.fft(tab_intermediate1*np.conj(tab_intermediate2))))))
      tab_after_fft = np.real(np.fft.fftshift(np.fft.fft(tab_intermediate1*np.conj(tab_intermediate2))))
      tab_wigner[0:dim_x//2,j,i] = tab_after_fft[0:dim_x:2]+tab_after_fft[1:dim_x:2]
  return tab_wigner


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

  if (rank==0):
    initial_time=time.asctime()
    hostname = os.uname()[1].split('.')[0]
    print("Python script started on: {}".format(initial_time))
    print("{:>24}: {}".format('from',hostname))
    print("Name of python script: {}".format(os.path.abspath( __file__ )))
#    print("Number of available threads: {}".format(multiprocessing.cpu_count()))
#    print("Number of disorder realizations: {}".format(n_config))

    timing=anderson.Timing()
    t1=time.perf_counter()

    config = configparser.ConfigParser()
    config.read('params.dat')

    Averaging = config['Averaging']
    n_config = Averaging.getint('n_config',1)
    n_config = (n_config+nprocs-1)//nprocs
    print("Total number of disorder realizations: {}".format(n_config*nprocs))
    print("Number of processes: {}".format(nprocs))

    System = config['System']
    system_size = System.getfloat('size')
    delta_x = System.getfloat('delta_x')
    boundary_condition = System.get('boundary_condition','periodic')

    Wavefunction = config['Wavefunction']
    initial_state_type = Wavefunction.get('initial_state')
    k_0 = 2.0*math.pi*Wavefunction.getfloat('k_0_over_2_pi')
    sigma_0 = Wavefunction.getfloat('sigma_0')

    Disorder = config['Disorder']
    disorder_type = Disorder.get('type','anderson_gaussian')
    print(disorder_type)
    correlation_length = Disorder.getfloat('sigma',0.0)
    V0 = Disorder.getfloat('V0',0.0)
    disorder_strength = V0

    Diagonalization = config['Diagonalization']
    diagonalization_method = Diagonalization.get('method','sparse')
    targeted_energy = Diagonalization.getfloat('targeted_energy')
    number_of_energy_levels = Diagonalization.getint('number_of_energy_levels',1)
    pivot_real = Diagonalization.getfloat('pivot_real')
    pivot_imag = Diagonalization.getfloat('pivot_imag')
    pivot = pivot_real+1j*pivot_imag
    IPR_min = Diagonalization.getfloat('IPR_min',0.0)
    IPR_max = Diagonalization.getfloat('IPR_max')
    number_of_bins = Diagonalization.getint('number_of_bins')
  else:
    n_config = None
    system_size = None
    delta_x = None
    boundary_condition = None
    disorder_type = None
    correlation_length = None
    disorder_strength = None
    diagonalization_method = None
    targeted_energy = None
 #  n_config = comm.bcast(n_config,root=0)

  if mpi_version:
    n_config, system_size, delta_x,boundary_condition  = comm.bcast((n_config, system_size,delta_x,boundary_condition ))
    disorder_type, correlation_length, disorder_strength = comm.bcast((disorder_type, correlation_length, disorder_strength))
    diagonalization_method, targeted_energy = comm.bcast((diagonalization_method, targeted_energy))

  timing=anderson.Timing()
  t1=time.perf_counter()

#  delta_x = comm.bcast(delta_x)
#  print(rank,n_config,system_size,delta_x)
    # Number of sites
  dim_x = int(system_size/delta_x+0.5)
    # Renormalize delta_x so that the system size is exactly what is wanted and split in an integer number of sites
  delta_x = system_size/dim_x
    #V0=0.025
    #disorder_strength = np.sqrt(V0)
  mkl.set_num_threads(1)
  os.environ["MKL_NUM_THREADS"] = "1"

  assert boundary_condition in ['periodic','open'], "Boundary condition must be either 'periodic' or 'open'"

  position = 0.5*delta_x*np.arange(1-dim_x,dim_x+1,2)
  # Prepare Hamiltonian structure (the disorder is NOT computed, as it is specific to each realization)
  H = anderson.Hamiltonian(dim_x, delta_x, boundary_condition=boundary_condition, disorder_type=disorder_type, correlation_length=correlation_length, disorder_strength=disorder_strength, interaction=0.0)
  initial_state = anderson.Wavefunction(dim_x,delta_x)
  initial_state.type = initial_state_type
  anderson.Wavefunction.gaussian(initial_state,k_0,sigma_0)
  initial_state.wfc*=np.sqrt(system_size)
  diagonalization = anderson.diag.Diagonalization(targeted_energy,diagonalization_method)
   #comm.Bcast(H)
  header_string = environment_string+anderson.io.output_string(H,n_config,nprocs,diagonalization=diagonalization)

  tab_spectrum = diagonalization.compute_full_spectrum(0, H)
  anderson.io.output_density('spectrum.dat',np.arange(dim_x),tab_spectrum,header_string,print_type='density')
  energy = np.zeros(number_of_energy_levels)
  tab_wfc = np.zeros((dim_x,number_of_energy_levels))
  energy, tab_wfc = diagonalization.compute_wavefunction(0, H, k=number_of_energy_levels)
  print('Energy = ',energy)
#  tab_wfc2 = np.zeros((dim_x,1),dtype=np.complex128)
#  tab_wfc2[:,0]=initial_state.wfc
#  np.savetxt('toto.dat',np.abs(tab_wfc2[:,0])**2)
  tab_wigner = compute_wigner_function(H,tab_wfc)
  for i in range(number_of_energy_levels):
    np.savetxt('wigner'+str(i)+'.dat',tab_wigner[:,:,i])
  anderson.io.output_density('potential.dat',position,H.disorder-2.0*H.tunneling,header_string,print_type='potential')
  landscape = diagonalization.compute_landscape_2(0,H,pivot)
  anderson.io.output_density('landscape.dat',position,landscape,header_string,print_type='wavefunction')
#  tab_IPR = np.zeros(n_config)
#  tab_energy = np.zeros(n_config)
  # Here starts the loop over disorder configurations
#  for i in range(n_config):
#    tab_energy[i], tab_IPR[i] = diagonalization.compute_IPR(i+rank*n_config, H)
#    print(IPR)
  #  pool.apply_async(gpe_evolution, args)
  #  print(str(i), file=final_pf)
#  anderson.io.output_density('IPR'+str(rank)+'.dat',tab_IPR,tab_energy,header_string,print_type='IPR')

#  if mpi_version:
#    start_mpi_time = timeit.default_timer()
#    tab_energy_glob = np.zeros(n_config*nprocs)
#    tab_IPR_glob = np.zeros(n_config*nprocs)
#    comm.Gather(tab_energy,tab_energy_glob)
#    comm.Gather(tab_IPR,tab_IPR_glob)
#    timing.MPI_TIME+=(timeit.default_timer() - start_mpi_time)
#  else:
#    tab_energy_glob = tab_energy
#    tab_IPR_glob = tab_IPR
  t2=time.perf_counter()
  timing.TOTAL_TIME = t2-t1
#  if mpi_version:
#    timing.mpi_merge(comm)
  if rank==0:
#    print(tab_IPR_glob.shape)
    anderson.io.output_density('wfc.dat',position,np.real(tab_wfc),header_string+'Energy = '+str(energy)+'\n',print_type='wavefunction_eigenstate')

    final_time = time.asctime()
    print("Python script ended on: {}".format(final_time))
    print("Wallclock time {0:.3f} seconds".format(t2-t1))
    print()
    if mpi_version:
      print("MPI time             = {0:.3f}".format(timing.MPI_TIME))
    print("Total_CPU time       = {0:.3f}".format(timing.TOTAL_TIME))

