#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Apr 15 11:22:51 2020

@author: delande
"""

import numpy as np
import copy
import configparser
import sys
import math
import anderson
#from anderson import geometry

def my_abort(mpi_version,comm,message):
  if mpi_version:
    print(message)
    comm.Abort()
  else:
    sys.exit(message)


def parse_parameter_file(mpi_version,comm,nprocs,rank,parameter_file,my_list_of_sections):
  if rank==0:
    config = configparser.ConfigParser()
    config.read(parameter_file)

# Mandatory Averaging section
    if not config.has_section('Averaging'):
      my_abort(mpi_version,comm,'Parameter file does not have an Averaging section, I stop!\n')
    Averaging = config['Averaging']
    n_config = Averaging.getint('n_config',1)
    n_config = (n_config+nprocs-1)//nprocs
    print("Total number of disorder realizations: {}".format(n_config*nprocs))
    print("Number of processes: {}".format(nprocs))
    print()

# Mandatory System section
    if not config.has_section('System'):
      my_abort(mpi_version,comm,'Parameter file does not have a System section, I stop!\n')
    System = config['System']
    dimension = System.getint('dimension', 1)
    one_over_mass = System.getfloat('one_over_mass', 1.0)
    use_mkl_fft = System.getboolean('use_mkl_fft',True)
    use_mkl_random = System.getboolean('use_mkl_random',True)
    reproducible_randomness = System.getboolean('reproducible_randomness',True)
    custom_seed = System.getint('custom_seed', 0)
    tab_size = list()
    tab_delta = list()
    tab_boundary_condition = list()
    all_options_ok = True
    for i in range(dimension):
      if not config.has_option('System','size_'+str(i+1)): all_options_ok=False
      if not config.has_option('System','delta_'+str(i+1)): all_options_ok=False
      if not config.has_option('System','boundary_condition_'+str(i+1)): all_options_ok=False
      tab_size.append(System.getfloat('size_'+str(i+1)))
      tab_delta.append(System.getfloat('delta_'+str(i+1)))
      tab_boundary_condition.append(System.get('boundary_condition_'+str(i+1),'periodic'))
      if not tab_boundary_condition[i] in ['periodic','open']: all_options_ok=False
    if not all_options_ok:
      my_abort(mpi_version,comm,'In the System section of the parameter file, each dimension must have a size, delta (discretization step) and boundary condition, I stop!\n')

#    print(dimension,tab_size,tab_delta,tab_boundary_condition)
# Number of sites
    tab_dim = list()
    for i in range(dimension):
      tab_dim.append(int(tab_size[i]/tab_delta[i]+0.5))
# Renormalize delta so that the system size is exactly what is wanted and split in an integer number of sites
      tab_delta[i] = tab_size[i]/tab_dim[i]
#  print(tab_dim)

# Mandatory Disorder section
    if not config.has_section('Disorder'):
      my_abort(mpi_version,comm,'Parameter file does not have a Disorder section, I stop!\n')
    Disorder = config['Disorder']
    disorder_type = Disorder.get('type','anderson_gaussian')
    randomize_hamiltonian = Disorder.getboolean('randomize_hamiltonian',True)
    if disorder_type=='nice' and dimension!=1:
      my_abort(mpi_version,comm,"The 'nice' disorder is implemented only in dimension 1, I stop!\n")
    if disorder_type=='speckle':
      if dimension<3:
        disorder_type = 'circular_speckle'
      else:
        disorder_type = 'spherical_speckle'
    correlation_length = Disorder.getfloat('sigma',0.0)
    V0 = Disorder.getfloat('V0',0.0)
    disorder_strength = V0
    non_diagonal_disorder_strength = Disorder.getfloat('non_diagonal_disorder_strength',0.0)
    b = Disorder.getint('b',1)
    
# Addition by JPB for the Palaiseau disorder
    wavelength_laser   = Disorder.getfloat('wavelength',0.0)
    diameter_diaphragm = Disorder.getfloat('diaphragm',0.0)
    waist_lense        = Disorder.getfloat('waist',0.0)
    focal_length       = Disorder.getfloat('focal',0.0)
    
# Optional Spin section
    if 'Spin' in my_list_of_sections:
      if not config.has_section('Spin'):
        spin_one_half = False
        spin_orbit_interaction = 0.0
        sigma_x = 0.0
        sigma_y = 0.0
        sigma_z = 0.0
        alpha = 0.0
#        my_abort(mpi_version,comm,'Parameter file does not have a Spin section, I stop!\n')
      else:
        Spin = config['Spin']
        spin_one_half = Spin.getboolean('spin_one_half',False)
#       if spin_one_half and dimension != 1:
#         my_abort(mpi_version,comm,'Spin 1/2 is supported only in dimension 1, I stop!\n')
        spin_orbit_interaction = Spin.getfloat('gamma',0.0)
        sigma_x = 0.5*Spin.getfloat('Omega',0.0)
        sigma_y = Spin.getfloat('beta',0.0)
        sigma_z = 0.5*Spin.getfloat('delta',0.0)
        alpha = Spin.getfloat('h',0.0)
    else:
      spin_one_half = False
      spin_orbit_interaction = 0.0
      sigma_x = 0.0
      sigma_y = 0.0
      sigma_z = 0.0
      alpha = 0.0
#    if spin_one_half and dimension!=1:
#      my_abort(mpi_version,comm,'Spin 1/2 works only in dimension 1, I stop!\n')

# Optional Nonlinearity section
    if 'Nonlinearity' in my_list_of_sections:
      if not config.has_section('Nonlinearity'):
        interaction_strength = 0.0
      else:
        Nonlinearity = config['Nonlinearity']
# First try to see if g_over_volume is defined
        interaction_strength = Nonlinearity.getfloat('g_over_volume')
# If not, try g
        if interaction_strength==None:
          interaction_strength = Nonlinearity.getfloat('g',0.0)
        else:
 # Multiply g_over_V by the volume of the system
          for i in range(dimension):
            interaction_strength *= tab_size[i]
#    print(interaction_strength)
    else:
      interaction_strength = 0.0

# Optional Wavefunction section
    if 'Wavefunction' in my_list_of_sections:
      if not config.has_section('Wavefunction'):
        my_abort(mpi_version,comm,'Parameter file does not have a Wavefunction section, I stop!\n')
      Wavefunction = config['Wavefunction']
      all_options_ok=True
      initial_state_type = Wavefunction.get('initial_state')
      randomize_initial_state = False
      minimum_distance = 0.0
      wfc_correlation_length = 0.0
      epsilon_speckle = 0.0
      if initial_state_type not in ["plane_wave","gaussian_wave_packet","gaussian_randomized","gaussian_with_speckle","chirped_wave_packet","point","multi_point","random"]: all_options_ok=False
#    assert initial_state_type in ["plane_wave","gaussian_wave_packet"], "Initial state is not properly defined"
      tab_k_0 = list()
      tab_sigma_0 = list()
      tab_chirp = list()
      if initial_state_type in ["plane_wave","gaussian_wave_packet","chirped_wave_packet"]:
        for i in range(dimension):
          if not config.has_option('Wavefunction','k_0_over_2_pi_'+str(i+1)): all_options_ok=False
#        tab_k_0.append(2.0*math.pi*
          k_0_over_2_pi=Wavefunction.getfloat('k_0_over_2_pi_'+str(i+1))
# k_0_over_2_pi*size must be an integer is all dimensions
# Renormalize k_0_over_2_pi to ensure it
          tab_k_0.append(2.0*math.pi*round(k_0_over_2_pi*tab_size[i])/tab_size[i])
          if initial_state_type != "plane_wave":
            if not config.has_option('Wavefunction','sigma_0_'+str(i+1)): all_options_ok=False
            tab_sigma_0.append(Wavefunction.getfloat('sigma_0_'+str(i+1)))
            if initial_state_type == "chirped_wave_packet":
              tab_chirp.append(Wavefunction.getfloat('chirp_'+str(i+1),0.0))
      if initial_state_type in ["gaussian_randomized"]:
        for i in range(dimension):
          if not config.has_option('Wavefunction','sigma_0_'+str(i+1)): all_options_ok=False
          tab_sigma_0.append(Wavefunction.getfloat('sigma_0_'+str(i+1)))
        randomize_initial_state = Wavefunction.getboolean('randomize_initial_state',False)
      if initial_state_type in ["gaussian_with_speckle"]:
        for i in range(dimension):
          if not config.has_option('Wavefunction','k_0_over_2_pi_'+str(i+1)): all_options_ok=False
          k_0_over_2_pi=Wavefunction.getfloat('k_0_over_2_pi_'+str(i+1))
# k_0_over_2_pi*size must be an integer is all dimensions
# Renormalize k_0_over_2_pi to ensure it
          tab_k_0.append(2.0*math.pi*round(k_0_over_2_pi*tab_size[i])/tab_size[i])
          if not config.has_option('Wavefunction','sigma_0_'+str(i+1)): all_options_ok=False
          tab_sigma_0.append(Wavefunction.getfloat('sigma_0_'+str(i+1)))
        randomize_initial_state = Wavefunction.getboolean('randomize_initial_state',True)
        wfc_correlation_length = Wavefunction.getfloat('wfc_correlation_length')
        epsilon_speckle = Wavefunction.getfloat('epsilon_speckle',0.0)
      if initial_state_type in ["multi_point","random"]:
        if spin_one_half:
          print('multi_point and random initial state are not yet implemented for spin-orbit systems, I switch to point initial state')
          initial_state_type = "point"
        else:
          minimum_distance = Wavefunction.getfloat('minimum_distance',0.0)
          randomize_initial_state = Wavefunction.getboolean('randomize_initial_state',True)
      if not all_options_ok:
        my_abort(mpi_version,comm,'In the Wavefunction section of the parameter file, some parameters are missing, I stop!\n')
      teta = Wavefunction.getfloat('teta',0.0)
      teta_measurement = Wavefunction.getfloat('teta_measurement',0.0)
#      print(teta,teta_measurement)
#      print(tab_k_0)




# Optional Propagation section
    if 'Propagation' in my_list_of_sections:
      if not config.has_section('Propagation'):
        my_abort(mpi_version,comm,'Parameter file does not have a Propagation section, I stop!\n')
      Propagation = config['Propagation']
      method = Propagation.get('method','che')
      accuracy = Propagation.getfloat('accuracy',1.e-6)
      accurate_bounds = Propagation.getboolean('accurate_bounds',False)
      want_ctypes = Propagation.getboolean('want_ctypes',True)
      data_layout = Propagation.get('data_layout','complex')
      t_max = Propagation.getfloat('t_max','0.0')
      delta_t = Propagation.getfloat('delta_t','0.0')
#      if spin_one_half and method=='che':
#        my_abort(mpi_version,comm,'Chebyshev propagation is not supported for spin_one_half, I stop!\n')
      if spin_one_half and data_layout=='real':
        my_abort(mpi_version,comm,'Real data layout is not supported for spin_one_half, I stop!\n')
#      if not all_options_ok:
#        my_abort(mpi_version,comm,'In the Propagation section of the parameter file, there must be a maximum propagation time t_max and a time step delta_t, I stop!\n')

# Optional Measurement section
    if 'Measurement' in my_list_of_sections:
      if not config.has_section('Measurement'):
        my_abort(mpi_version,comm,'Parameter file does not have a Measurement section, I stop!\n')
      if not config.has_section('Propagation'):
        my_abort(mpi_version,comm,'Parameter file has a Measurement section, but no Propagation section, I stop!\n')
      Measurement = config['Measurement']
      delta_t_dispersion = Measurement.getfloat('delta_t_dispersion',delta_t)
      delta_t_density = Measurement.getfloat('delta_t_density',t_max)
      delta_t_spectral_function = Measurement.getfloat('delta_t_spectral_function',t_max)
      measure_potential = Measurement.getboolean('potential',False)
      measure_potential_correlation = Measurement.getboolean('potential_correlation',False)
      measure_density = Measurement.getboolean('density',False)
      measure_density_momentum = Measurement.getboolean('density_momentum',False)
      measure_autocorrelation = Measurement.getboolean('autocorrelation',False)
      measure_dispersion_position = Measurement.getboolean('dispersion_position',False)
      measure_dispersion_position2 = Measurement.getboolean('dispersion_position2',False)
      measure_dispersion_momentum = Measurement.getboolean('dispersion_momentum',False)
      measure_dispersion_energy = Measurement.getboolean('dispersion_energy',False)
      measure_wavefunction = Measurement.getboolean('wavefunction',False)
      measure_wavefunction_momentum = Measurement.getboolean('wavefunction_momentum',False)
      measure_extended = Measurement.getboolean('dispersion_variance',False)
      measure_g1 = Measurement.getboolean('g1',False)
      measure_overlap = Measurement.getboolean('overlap',False)
      measure_spectral_function = Measurement.getboolean('spectral_function',False)
      if measure_spectral_function and not 'Spectral' in my_list_of_sections:
        my_abort(mpi_version,comm,'Measurement section requires to measure the spectral function, but there is no Spectral section in the parameter file, I stop!\n')
      remove_hot_pixel = Measurement.getboolean('remove_hot_pixel',False)

# Optional Diagonalization section
    if 'Diagonalization' in my_list_of_sections:
      if not config.has_section('Diagonalization'):
        my_abort(mpi_version,comm,'Parameter file does not have a Diagonalization section, I stop!\n')
      Diagonalization = config['Diagonalization']
      diagonalization_method = Diagonalization.get('method','sparse')
      targeted_energy = Diagonalization.getfloat('targeted_energy')
      IPR_min = Diagonalization.getfloat('IPR_min',0.0)
      IPR_max = Diagonalization.getfloat('IPR_max',1.0)
      number_of_bins = Diagonalization.getint('number_of_bins',1)
      number_of_eigenvalues = Diagonalization.getint('number_of_eigenvalues',1)

# Optional Spectral section
# Default values (should never be used, only to ensure they are defined for MPI broadcasting)
    spectre_min = None
    spectre_max = None
    spectre_resolution = None
    n_kpm = 0
    want_ctypes_for_spectral_function = True
    allow_unsafe_energy_bounds = False
    multiplicative_factor_for_interaction_in_spectral_function = 0.0
    if ('Measurement' in my_list_of_sections and measure_spectral_function) or ('Measurement' not in my_list_of_sections and 'Spectral' in my_list_of_sections):
      if not config.has_section('Spectral'):
        my_abort(mpi_version,comm,'Parameter file does not have a Spectral section, I stop!\n')
      Spectral = config['Spectral']
      all_options_ok = True
      spectre_min = Spectral.getfloat('e_min')
      spectre_max = Spectral.getfloat('e_max')
      if spectre_min==None or spectre_max==None:
        if not config.has_option('Spectral','range'):
          all_options_ok = False
        else:
          e_range = Spectral.getfloat('range')
          spectre_min = -0.5*e_range
          spectre_max =  0.5*e_range
      if not config.has_option('Spectral','resolution'): all_options_ok = False
      spectre_resolution = Spectral.getfloat('resolution')
      multiplicative_factor_for_interaction_in_spectral_function = Spectral.getfloat('multiplicative_factor_for_interaction',0.0)
      n_kpm = Spectral.getint('n_kpm',0)
# Determine the default value of n_kpm
      if n_kpm==0:
        n_kpm=int(0.5*(spectre_max-spectre_min)/spectre_resolution)
      want_ctypes_for_spectral_function = Spectral.getboolean('want_ctypes_for_spectral_function',True)
      allow_unsafe_energy_bounds = Spectral.getboolean('allow_unsafe_energy_bounds',False)
      if not all_options_ok:
        my_abort(mpi_version,comm,'In the Spectral section of the parameter file, there must be a resolution and either an energy interval [e_min,e_max] or an energy range e_range, I stop!\n')


# Optional Lyapounov section
    if 'Lyapounov' in my_list_of_sections:
      if not config.has_section('Lyapounov'):
        my_abort(mpi_version,comm,'Parameter file does not have a Lyapounov section, I stop!\n')
      Lyapounov = config['Lyapounov']
#      e_min = Lyapounov.getfloat('e_min',0.0)
#      e_max = Lyapounov.getfloat('e_max',0.0)
#      number_of_e_steps = Lyapounov.getint('number_of_e_steps',0)
      energy = Lyapounov.getfloat('energy',0.0)
      i0 = Lyapounov.getint('number_of_skipped_layers',10)
      nrescale = Lyapounov.getint('nrescale',10)
      if i0%nrescale!=0:
        i0 = ((i0-1)//nrescale+1)*nrescale
        print('Info: number_of_skipped_layers must be an integer multiple of nrescale. It is changed to',i0,'\n')
#      e_histogram = Lyapounov.getfloat('e_histogram',0.0)
#      lyapounov_min = Lyapounov.getfloat('lyapounov_min',0.0)
#      lyapounov_max = Lyapounov.getfloat('lyapounov_max',0.0)
#      number_of_bins = Lyapounov.getint('number_of_bins',0)
      want_ctypes_for_lyapounov = Lyapounov.getboolean('want_ctypes',True)
      tab_boundary_condition[0] = 'open'


  else:
    dimension = None
    one_over_mass = None
    n_config = None
    tab_size = None
    tab_delta = None
    tab_dim = None
    tab_boundary_condition = None
    reproducible_randomness = None
    custom_seed = None
    disorder_type = None
    randomize_hamiltonian = None
    correlation_length = None
    disorder_strength = None
    non_diagonal_disorder_strength = None
    b = None
    use_mkl_random = None
    use_mkl_fft = None
    spin_one_half = None
    spin_orbit_interaction = None
    sigma_x = None
    sigma_y = None
    sigma_z = None
    alpha = None
    interaction_strength = None
    initial_state_type = None
    minimum_distance = None
    randomize_initial_state = None
    tab_k_0 = None
    tab_sigma_0 = None
    tab_chirp = None
    wfc_correlation_length = None
    epsilon_speckle = None
    teta = None
    teta_measurement = None
    method = None
    accuracy = None
    accurate_bounds = None
    want_ctypes = None
    data_layout = None
    t_max = None
    delta_t = None
    delta_t_dispersion = None
    delta_t_density = None
    delta_t_spectral_function = None
    measure_potential = None
    measure_potential_correlation = None
    measure_density = None
    measure_density_momentum = None
    measure_autocorrelation = None
    measure_dispersion_position = None
    measure_dispersion_position2 = None
    measure_dispersion_momentum = None
    measure_dispersion_energy = None
    measure_wavefunction = None
    measure_wavefunction_momentum = None
    measure_extended = None
    measure_g1 = None
    measure_overlap = None
    measure_spectral_function = None
    remove_hot_pixel = None
    diagonalization_method = None
    targeted_energy = None
    IPR_min = None
    IPR_max = None
    number_of_bins = None
    number_of_eigenvalues = None
    spectre_min = None
    spectre_max = None
    spectre_resolution = None
    multiplicative_factor_for_interaction_in_spectral_function = None
    n_kpm = None
    want_ctypes_for_spectral_function = None
    allow_unsafe_energy_bounds = None
#    e_min = None
#    e_max = None
#    number_of_e_steps = None
#    e_histogram = None
#    lyapounov_min = None
#    lyapounov_max = None
    energy = None
    want_ctypes_for_lyapounov = None
    i0 = None
    nrescale = None


  if mpi_version:
    n_config, dimension, one_over_mass, tab_size, tab_delta, tab_dim, tab_boundary_condition, use_mkl_random, use_mkl_fft, reproducible_randomness, custom_seed  = \
      comm.bcast((n_config, dimension, one_over_mass, tab_size,tab_delta, tab_dim, tab_boundary_condition, use_mkl_random, use_mkl_fft, reproducible_randomness, custom_seed))
    disorder_type, randomize_hamiltonian, correlation_length, disorder_strength, non_diagonal_disorder_strength, b, interaction_strength = \
      comm.bcast((disorder_type, randomize_hamiltonian, correlation_length, disorder_strength, non_diagonal_disorder_strength, b, interaction_strength))
    if 'Spin' in my_list_of_sections:
      spin_one_half, spin_orbit_interaction, sigma_x, sigma_y, sigma_z, alpha = \
        comm.bcast((spin_one_half, spin_orbit_interaction, sigma_x, sigma_y, sigma_z, alpha))
    if 'Wavefunction' in my_list_of_sections:
      initial_state_type, minimum_distance, randomize_initial_state, tab_k_0, tab_sigma_0, tab_chirp, wfc_correlation_length, epsilon_speckle, teta, teta_measurement = \
        comm.bcast((initial_state_type, minimum_distance, randomize_initial_state, tab_k_0, tab_sigma_0, tab_chirp, wfc_correlation_length, epsilon_speckle, teta, teta_measurement))
    if 'Propagation' in my_list_of_sections:
      method, accuracy, accurate_bounds, want_ctypes, data_layout, t_max, delta_t = comm.bcast((method, accuracy, accurate_bounds, want_ctypes, data_layout, t_max, delta_t))
    if 'Measurement' in my_list_of_sections:
      delta_t_dispersion, delta_t_density, delta_t_spectral_function, teta_measurement, measure_potential, measure_potential_correlation, \
        measure_density, measure_density_momentum, measure_autocorrelation, measure_dispersion_position, measure_dispersion_position2, \
        measure_dispersion_momentum, measure_dispersion_energy, measure_wavefunction, measure_wavefunction_momentum, \
        measure_extended, measure_g1, measure_overlap, measure_spectral_function, remove_hot_pixel = \
      comm.bcast((delta_t_dispersion, delta_t_density, delta_t_spectral_function, teta_measurement, measure_potential, measure_potential_correlation, \
        measure_density, measure_density_momentum, measure_autocorrelation, measure_dispersion_position,  measure_dispersion_position2, \
        measure_dispersion_momentum, measure_dispersion_energy, measure_wavefunction, measure_wavefunction_momentum, \
        measure_extended, measure_g1, measure_overlap, measure_spectral_function, remove_hot_pixel))
    if 'Diagonalization' in my_list_of_sections:
      diagonalization_method, targeted_energy, IPR_min, IPR_max, number_of_bins, number_of_eigenvalues  = \
        comm.bcast((diagonalization_method, targeted_energy, IPR_min, IPR_max, number_of_bins, number_of_eigenvalues))
    if 'Spectral' in my_list_of_sections:
      spectre_min, spectre_max, spectre_resolution, multiplicative_factor_for_interaction_in_spectral_function, n_kpm, want_ctypes_for_spectral_function, allow_unsafe_energy_bounds = \
        comm.bcast((spectre_min, spectre_max, spectre_resolution,multiplicative_factor_for_interaction_in_spectral_function, n_kpm, want_ctypes_for_spectral_function, allow_unsafe_energy_bounds))
    if 'Lyapounov' in my_list_of_sections:
#      e_min, e_max, number_of_e_steps, e_histogram, lyapounov_min, lyapounov_max, number_of_bins, want_ctypes_for_lyapounov, i0, nrescale = \
#        comm.bcast((e_min, e_max, number_of_e_steps, e_histogram, lyapounov_min, lyapounov_max, number_of_bins, want_ctypes_for_lyapounov, i0, nrescale))
      energy, want_ctypes_for_lyapounov, i0, nrescale = \
        comm.bcast((energy, want_ctypes_for_lyapounov, i0, nrescale))


  geometry = anderson.geometry.Geometry(dimension, tab_dim, tab_delta, use_mkl_random=use_mkl_random, use_mkl_fft=use_mkl_fft, spin_one_half=spin_one_half, reproducible_randomness=reproducible_randomness, custom_seed=custom_seed )
# Prepare Hamiltonian structure (the disorder is NOT computed, as it is specific to each realization)
  H = anderson.hamiltonian.Hamiltonian(geometry, tab_boundary_condition=tab_boundary_condition, one_over_mass=one_over_mass, \
      disorder_type=disorder_type, randomize_hamiltonian=randomize_hamiltonian, correlation_length=correlation_length, disorder_strength=disorder_strength, non_diagonal_disorder_strength=non_diagonal_disorder_strength, \
      b=b, interaction=interaction_strength)
#  print(H.randomize_hamiltonian)
  if spin_one_half:
    H.add_spin_one_half(spin_orbit_interaction=spin_orbit_interaction, sigma_x=sigma_x, sigma_y=sigma_y, sigma_z=sigma_z, alpha=alpha)
  return_list = [geometry, H]

# Define an initial state
  if 'Wavefunction' in my_list_of_sections:
    initial_state = anderson.wavefunction.Wavefunction(geometry)
    initial_state.type = initial_state_type
    initial_state.randomize_initial_state = randomize_initial_state
    initial_state.wfc_correlation_length = wfc_correlation_length
    initial_state.epsilon_speckle = epsilon_speckle
    if spin_one_half:
      initial_state.lhs_state = np.array([np.cos(teta),np.sin(teta)])
      initial_state.teta = teta
    else:
      initial_state.lhs_state = None
    initial_state.minimum_distance = minimum_distance
    initial_state.tab_k_0 = tab_k_0
    initial_state.tab_sigma_0 = tab_sigma_0
    initial_state.tab_chirp = tab_chirp
    return_list.append(initial_state)

# Define the structure of spectral_function
  if ('Measurement' in my_list_of_sections and measure_spectral_function) or ('Measurement' not in my_list_of_sections and 'Spectral' in my_list_of_sections):
 # if 'Spectral' in my_list_of_sections:
#    measure_spectral_function_local = not 'Measurement' in my_list_of_sections
#    measure_spectral_function_local = True
    spectral_function = anderson.propagation.Spectral_function(spectre_min,spectre_max,spectre_resolution,multiplicative_factor_for_interaction_in_spectral_function, n_kpm, want_ctypes_for_spectral_function, allow_unsafe_energy_bounds, H)
#    propagation_spectral = anderson.propagation.Temporal_Propagation(spectral_function.t_max,spectral_function.delta_t,method=method, accuracy=accuracy, accurate_bounds=accurate_bounds, data_layout=data_layout,want_ctypes=want_ctypes, H=H)
#    return_list.append(propagation_spectral)
#    measurement_spectral = anderson.measurement.Measurement(geometry, spectral_function.delta_t, spectral_function.t_max, spectral_function.t_max, \
#      measure_autocorrelation=True, measure_spectral_function=measure_spectral_function_local, \
#      measure_potential=measure_potential, measure_potential_correlation=measure_potential_correlation, use_mkl_fft=use_mkl_fft)
#    measurement_spectral_global = copy.deepcopy(measurement_spectral)
#    print("Calling prepare_measurement from the Spectral section")
#    measurement_spectral.prepare_measurement(propagation_spectral,spectral_function=spectral_function,is_spectral_function=True,is_inner_spectral_function=not measure_spectral_function_local)
#    print(measurement_spectral.tab_spectrum)
#    measurement_spectral_global.prepare_measurement(propagation_spectral,spectral_function=spectral_function,is_spectral_function=True,is_inner_spectral_function=not measure_spectral_function_local,global_measurement=True)
#    measurement_spectral.tab_time[:,3]=0
#    measurement_spectral_global.tab_time[:,3]=0
#    return_list.append(measurement_spectral)
#    return_list.append(measurement_spectral_global)
  else:
    spectral_function = None
  return_list.append(spectral_function)

# Define the structure of measurements
  if 'Measurement' in my_list_of_sections:
# Define the structure of the temporal integration
    propagation = anderson.propagation.Temporal_Propagation(t_max, delta_t, method=method, accuracy=accuracy, accurate_bounds=accurate_bounds, data_layout=data_layout,want_ctypes=want_ctypes, H=H)
    return_list.append(propagation)
    measurement = anderson.measurement.Measurement(geometry, delta_t_dispersion, delta_t_density, delta_t_spectral_function, \
      teta_measurement=teta_measurement, measure_potential=measure_potential, measure_potential_correlation=measure_potential_correlation, \
      measure_density=measure_density, measure_density_momentum=measure_density_momentum, measure_autocorrelation=measure_autocorrelation, \
      measure_dispersion_position=measure_dispersion_position, measure_dispersion_position2=measure_dispersion_position2, \
      measure_dispersion_momentum=measure_dispersion_momentum, measure_dispersion_energy=measure_dispersion_energy, \
      measure_wavefunction=measure_wavefunction, measure_wavefunction_momentum=measure_wavefunction_momentum, \
      measure_extended=measure_extended,measure_g1=measure_g1, measure_overlap=measure_overlap, measure_spectral_function=measure_spectral_function, \
      use_mkl_fft=use_mkl_fft, remove_hot_pixel=remove_hot_pixel)
    measurement_global = copy.deepcopy(measurement)
#  print(measurement.measure_density,measurement.measure_autocorrelation,measurement.measure_dispersion,measurement.measure_dispersion_momentum)
#    print(delta_t,propagation.delta_t)
    measurement.prepare_measurement(propagation,spectral_function=spectral_function)
#  print(measurement.density_final.shape)
    measurement_global.prepare_measurement(propagation,spectral_function=spectral_function,global_measurement=True)
    return_list.append(measurement)
    return_list.append(measurement_global)

# Define the structure of diagonalization
  if 'Diagonalization' in my_list_of_sections:
    diagonalization = anderson.diag.Diagonalization(targeted_energy,method=diagonalization_method, IPR_min= IPR_min, IPR_max=IPR_max, number_of_bins=number_of_bins, number_of_eigenvalues=number_of_eigenvalues)
    return_list.append(diagonalization)

# Define the structure of lyapounov
  if 'Lyapounov' in my_list_of_sections:
    lyapounov = anderson.lyapounov.Lyapounov(energy=energy,want_ctypes=want_ctypes_for_lyapounov, i0=i0, nrescale=nrescale)
    return_list.append(lyapounov)

  return_list.append(n_config)
#  print(return_list)
  return(return_list)

# DD, August, 11, 2023
# IMPORTANT
# When the disorder type is 'palaiseau', the output file should contain the parameters of the llaser beam
def output_string(H,n_config,nprocs=1,propagation=None,initial_state=None,measurement=None,spectral_function=None,diagonalization=None,lyapounov=None,timing=None):
#  print(spectral_function)
  params_string = 'Dimension                               = '+str(H.dimension)+'\n'
  volume = 1.0
  for i in range(H.dimension):
    volume *= H.tab_dim[i]*H.tab_delta[i]
    params_string += \
                  'Size_'+str(i+1)+'                                  = '+str(H.tab_dim[i]*H.tab_delta[i])+'\n'\
                 +'delta_'+str(i+1)+'                                 = '+str(H.tab_delta[i])+'\n'\
                 +'N_'+str(i+1)+'                                     = '+str(H.tab_dim[i])+'\n'\
                 +'Boundary_Condition_'+str(i+1)+'                    = '+H.tab_boundary_condition[i]+'\n'
  params_string += \
                  'Volume                                  = '+str(volume)+'\n'\
                 +'1/mass                                  = '+str(H.one_over_mass)+'\n'
  if H.spin_one_half:
    params_string += \
                  'Spin 1/2                                = True\n'\
                 +'gamma (p sigma_z)                       = '+str(H.spin_orbit_interaction)+'\n'\
                 +'Omega (sigma_x/2)                       = '+str(2.0*H.sigma_x)+'\n'\
                 +'beta (sigma_y)                          = '+str(H.sigma_y)+'\n'\
                 +'delta (sigma_z/2)                       = '+str(2.0*H.sigma_z)+'\n'\
                 +'h (p^2 sigma_z)                         = '+str(H.alpha)+'\n'
  params_string += \
                  'Disorder type                           = '+H.disorder_type+'\n'\
                 +'randomize disorder for each config      = '+str(H.randomize_hamiltonian)+'\n'\
                 +'Use reproducible randomness             = '+str(H.reproducible_randomness)+'\n'
  if H.reproducible_randomness:
    params_string += \
                  'Custom seed for random number generator = '+str(H.custom_seed)+'\n'\
                 +'use MKL random number generator         = '+str(H.use_mkl_random)+'\n'\
                 +'use MKL FFT                             = '+str(H.use_mkl_fft)+'\n'
  params_string += \
                  'V0                                      = '+str(H.disorder_strength)+'\n'
  if H.disorder_type not in ['anderson_gaussian','anderson_uniform','anderson_cauchy','nice']:
    params_string += \
                  'Correlation length                      = '+str(H.correlation_length)+'\n'
  if H.disorder_type=='nice':
    params_string += \
                  'Non diagonal disorder strength          = '+str(H.non_diagonal_disorder_strength)+'\n'\
                 +'Number of non diagonal channels         = '+str(H.b)+'\n'
  params_string += \
                  'g                                       = '+str(H.interaction)+'\n'\
                 +'g_over_volume                           = '+str(H.interaction/volume)+'\n'\
                 +'Number of disorder realizations         = '+str(n_config*nprocs)+'\n'\
                 +'Number of processes                     = '+str(nprocs)+'\n'\
                 +'Number of realizations per process      = '+str(n_config)+'\n'
  if not initial_state == None:
#    print(initial_state.type)
    params_string += \
                  'Initial state                           = '+initial_state.type+'\n'
    if initial_state.type in ['plane_wave','gaussian_wave_packet','chirped_wave_packet','gaussian_with_speckle']:
      for i in range(H.dimension):
        params_string += \
                  'k_0_'+str(i+1)+'                                   = '+str(initial_state.tab_k_0[i])+'\n'
        if initial_state.type in ['gaussian_wave_packet','gaussian_with_speckle']:
          params_string += \
                  'sigma_0_'+str(i+1)+'                               = '+str(initial_state.tab_sigma_0[i])+'\n'
        if initial_state.type == 'chirped_wave_packet':
          params_string += \
                  'sigma_0_'+str(i+1)+'                               = '+str(initial_state.tab_sigma_0[i])+'\n'\
                 +'chirp_'+str(i+1)+'                                 = '+str(initial_state.tab_chirp[i])+'\n'
    if initial_state.type == 'gaussian_with_speckle':
      params_string += \
                  'correlation length of the speckle       = '+str(initial_state.wfc_correlation_length)+'\n'\
                  'weight of the speckle/background        = '+str(initial_state.epsilon_speckle)+'\n'
    if initial_state.type == 'multi_point':
      params_string += \
                  'minimum distance between points         = '+str(initial_state.minimum_distance)+'\n'
    if initial_state.type in ['multi_point','random','gaussian_randomized','gaussian_with_speckle']:
      params_string += \
                  'randomize initial state for each config = '+str(initial_state.randomize_initial_state)+'\n'
    if H.spin_one_half:
      params_string += \
                  'teta                                    = '+str(initial_state.teta)+' \n'\
                 +'teta_measurement                        = '+str(measurement.teta_measurement)+'\n'
  if not propagation == None:
    params_string += \
                  'Integration Method                      = '+propagation.method+'\n'\
                 +'accuracy                                = '+str(propagation.accuracy)+'\n'
    if propagation.method=='che':
      params_string += \
                  'accurate spectrum bounds                = '+str(propagation.accurate_bounds)+'\n'\
                 +'use ctypes implementation               = '+str(propagation.use_ctypes)+'\n'\
                 +'use specific full Chebyshev routine     = '+str(propagation.has_specific_full_chebyshev_routine)+'\n'\
                 +'use specific Chebyshev step routine     = '+str(propagation.has_specific_chebyshev_step_routine)+'\n'\
                 +'use specific H|psi> routine             = '+str(H.has_specific_apply_h_routine)+'\n'
      if not timing==None:
        params_string += \
                  'maximum Chebyshev order                 = '+str(timing.MAX_CHE_ORDER)+'\n'\
                 +'maximum non-linear phase                = '+str(timing.MAX_NONLINEAR_PHASE)+'\n'
    params_string += \
                  'data layout                             = '+propagation.data_layout+'\n'\
                 +'time step                               = '+str(propagation.delta_t)+'\n'\
                 +'total time                              = '+str(propagation.t_max)+'\n'
  if not measurement == None:
    params_string += \
                  'time step for dispersion measurement    = '+str(measurement.delta_t_dispersion)+'\n'\
                 +'time step for density measurement       = '+str(measurement.delta_t_density)+'\n'
    if measurement.measure_spectral_function:
      params_string +=\
                  'time step for spectral function         = '+str(measurement.delta_t_spectral_function)+'\n'
    if initial_state.type=='plane_wave':
      params_string += \
                  'remove hot pixel in momentum density    = '+str(measurement.remove_hot_pixel)+'\n'
    if measurement.measure_overlap:
      params_string += \
                  '|overlap|**2 with initial state         = '+str(abs(measurement.overlap)**2)+'\n'
  if (not measurement == None and measurement.measure_spectral_function) or (not spectral_function == None):
    params_string += \
                  'minimum energy for spectral function    = '+str(spectral_function.e_min)+'\n'\
                 +'maximum energy for spectral function    = '+str(spectral_function.e_max)+'\n'\
                 +'energy resolution                       = '+str(spectral_function.e_resolution)+'\n'\
                 +'multiplicative factor for interaction   = '+str(spectral_function.multiplicative_factor_for_interaction)+'\n'\
                 +'kpm order                               = '+str(spectral_function.n_kpm)+'\n'\
                 +'use ctypes implementation               = '+str(spectral_function.use_ctypes)+'\n'
  if not diagonalization == None:
    params_string += \
                  'targeted_energy                         = '+str(diagonalization.targeted_energy)+'\n'\
                 +'diagonalization method                  = '+diagonalization.method+'\n'\
                 +'number of computed eigenvalues          = '+str(diagonalization.number_of_eigenvalues)+'\n'
  if not lyapounov == None:
    params_string += \
                  'energy                                  = '+str(lyapounov.energy)+'\n'\
                 +'use ctypes implementation               = '+str(lyapounov.use_ctypes)+'\n'\
                 +'number of skipped layers                = '+str(lyapounov.i0)+'\n'\
                 +'nrescale                                = '+str(lyapounov.nrescale)+'\n'
  params_string += '\n'
  return params_string



def output_density(file,data,geometry,header_string='Origin of data not specified',data_type='density',tab_abscissa=[],file_type='savetxt'):
#  print(data.shape)
#  print(tab_abscissa)
  if file_type=='savetxt':
    if data_type=='potential':
      column_1='Position'
      column_2='Disordered potential'
      specific_string='Disordered potential\n'
    if data_type=='potential_correlation':
      column_1='Relative position'
      column_2='Disordered potential correlation function'
      specific_string='Disordered potential correlation function\n'
    if data_type=='density':
      column_1='Position'
      column_2='Density'
      column_3='Std. deviation of density'
      specific_string='Spatial density\n'
    if data_type=='density_momentum':
      column_1='Momentum'
      column_2='Density'
      column_3='Std. deviation of density'
      specific_string='Density in momentum space\n'
    if data_type=='wavefunction':
      column_1='Position'
      if geometry.spin_one_half:
        column_2='Re(wavefunction) spin up'
        column_3='Im(wavefunction) spin up'
        column_4='Re(wavefunction) spin down'
        column_5='Im(wavefunction) spin down'
      else:
        column_2='Re(wavefunction)'
        column_3='Im(wavefunction)'
      specific_string='Wavefunction in configuration space\n'
    if data_type=='wavefunction_momentum':
      column_1='Momentum'
      column_2='Re(wavefunction)'
      column_3='Im(wavefunction)'
      specific_string='Wavefunction in momentum space\n'
    if data_type=='autocorrelation':
      column_1='Time'
      column_2='Re(<psi(0)|psi(t)>)'
      column_3='Im(<psi(0)|psi(t)>)'
      specific_string='Temporal autocorrelation function\n'
    if data_type=='spectral_function':
      column_1='Energy'
      column_2='Spectral function'
      specific_string='Spectral function\n'
    if data_type=='density_of_states':
      column_1='Energy'
      column_2='Density of states'
      specific_string='Density of states\n'
    if data_type=='g1':
      column_1='Relative position'
      column_2='Re(g1)'
      column_3='Im(g1)'
      specific_string='g1 correlation function\n'
    if data_type=='IPR':
      column_1='IPR'
      specific_string='Inverse participation ratio for the eigenstate closer to the targeted energy\n'\
                   +'Average IPR           = '+str(np.mean(data))+'\n'\
                   +'Std. deviation of IPR = '+str(np.std(data))+'\n'
    if data_type=='histogram_IPR':
      column_1 = 'Right bin edge'
      column_2 = 'Normalized distribution'
      specific_string='Distribution of the inverse participation ratio for the eigenstates closer to the targeted energy\n'
    if data_type=='rbar':
      column_1 = 'Energy'
      column_2 = 'rbar value'
      specific_string='rbar value\n'
    if data_type=='histogram_r':
      column_1 = 'Right bin edge'
      column_2 = 'Normalized distribution'
      specific_string='Distribution of the r value for the eigenstates closer to the targeted energy\n'
    if data_type=='lyapounov':
      column_1 = 'V0'
      column_2 = 'Energy'
      column_3 = 'Lyapounov for the wavefunction (double it for intensity)'
      column_4 = 'Std. deviation of Lyapounov'
      column_5 = 'Localization length for wavefunction (halve it for intensity)'
      column_6 = 'Std. deviation of localization length'
      specific_string='Lyapounov and localization length\n'
    list_of_columns = []
    tab_strings = []
#    print(specific_string)
    next_column = 1
    dimension = geometry.dimension
    if data_type in ['potential','potential_correlation','density','density_momentum']:
#      print(data.ndim,data.shape)
# The simple case where there is only 1d data
      if dimension==1:
        if data_type=='potential':
          header_string=str(geometry.tab_dim[0])+' '+str(geometry.tab_delta[0])+'\n'+header_string
        if data_type=='potential_correlation':
          header_string=str(geometry.tab_dim[0])+' '+str(geometry.tab_delta[0])+'\n'+header_string
        if data_type=='density':
          header_string=str(geometry.tab_dim[0])+' '+str(geometry.tab_delta[0])+'\n'+header_string
        if data_type=='density_momentum':
          header_string=str(geometry.tab_dim[0])+' '+str(2.0*np.pi/(geometry.tab_dim[0]*geometry.tab_delta[0]))+'\n'+header_string
#        print('toto', data.ndim)
        if data.ndim==1:
#          print('tototo')
          if tab_abscissa!=[]:
#            print('totototo')
            if data_type=='potential_correlation':
              list_of_columns.append(tab_abscissa[0]-0.5*geometry.tab_delta[0])
            else:
              list_of_columns.append(tab_abscissa[0])
          tab_strings.append('Column '+str(next_column)+': '+column_1)
          next_column += 1
          list_of_columns.append(data)
          tab_strings.append('Column '+str(next_column)+': '+column_2)
          next_column += 1
          array_to_print=np.column_stack(list_of_columns)
        if data.ndim==2:
#          print(data.shape[1],tab_abscissa[0].size)
          if tab_abscissa!=[] and data.shape[1]==tab_abscissa[0].size:
            list_of_columns.append(tab_abscissa[0])
            tab_strings.append('Column '+str(next_column)+': '+column_1)
            next_column += 1
          list_of_columns.append(data[0,:])
          tab_strings.append('Column '+str(next_column)+': '+column_2)
          next_column += 1
          if data.shape[0]==2:
            list_of_columns.append(data[1,:])
            tab_strings.append('Column '+str(next_column)+': '+column_3)
            next_column += 1
          array_to_print=np.column_stack(list_of_columns)
      if dimension==2:
 # Add at the beginning of the file minimal info describing the data
        if data_type=='density':
#          print('toto')
          header_string=str(geometry.tab_dim[0])+' '+str(geometry.tab_delta[0])+'\n'\
                       +str(geometry.tab_dim[1])+' '+str(geometry.tab_delta[1])+'\n'\
                       +header_string
        if data_type=='potential':
          header_string=str(geometry.tab_dim[0])+' '+str(geometry.tab_delta[0])+'\n'\
                       +str(geometry.tab_dim[1])+' '+str(geometry.tab_delta[1])+'\n'\
                       +header_string
        if data_type=='potential_correlation':
          header_string=str(geometry.tab_dim[0])+' '+str(geometry.tab_delta[0])+'\n'\
                       +str(geometry.tab_dim[1])+' '+str(geometry.tab_delta[1])+'\n'\
                       +header_string
        if data_type=='density_momentum':
          header_string=str(geometry.tab_dim[0])+' '+str(2.0*np.pi/(geometry.tab_dim[0]*geometry.tab_delta[0]))+'\n'\
                       +str(geometry.tab_dim[1])+' '+str(2.0*np.pi/(geometry.tab_dim[1]*geometry.tab_delta[1]))+'\n'\
                       +header_string
        if data.ndim==2:
          array_to_print = data[:,:]
        if data.ndim==3:
          array_to_print=data[0,:,:]
      if dimension==3:
 # Add at the beginning of the file minimal info describing the data
        if data_type in ['density','potential','potential_correlation']:
          header_string=str(geometry.tab_dim[0])+' '+str(geometry.tab_delta[0])+'\n'\
                       +str(geometry.tab_dim[1])+' '+str(geometry.tab_delta[1])+'\n'\
                       +str(geometry.tab_dim[2])+' '+str(geometry.tab_delta[2])+'\n'\
                       +header_string
        if data_type=='density_momentum':
          header_string=str(geometry.tab_dim[0])+' '+str(2.0*np.pi/(geometry.tab_dim[0]*geometry.tab_delta[0]))+'\n'\
                       +str(geometry.tab_dim[1])+' '+str(2.0*np.pi/(geometry.tab_dim[1]*geometry.tab_delta[1]))+'\n'\
                       +str(geometry.tab_dim[2])+' '+str(2.0*np.pi/(geometry.tab_dim[2]*geometry.tab_delta[2]))+'\n'\
                       +header_string
        if data.ndim==3:
          array_to_print = data[:,:,:]
        if data.ndim==4:
          array_to_print=data[0,:,:,:]
    if data_type in ['wavefunction','wavefunction_momentum','g1']:
      if dimension==1:
        if data_type=='g1' or data_type=='wavefunction':
          header_string=str(geometry.tab_dim[0])+' '+str(geometry.tab_delta[0])+'\n'+header_string
        if data_type=='wavefunction_momentum':
          header_string=str(geometry.tab_dim[0])+' '+str(2.0*np.pi/(geometry.tab_dim[0]*geometry.tab_delta[0]))+'\n'+header_string
#        print(data.size,tab_abscissa[0].size)
#        if tab_abscissa!=[] and data.size==tab_abscissa[0].size:
        if tab_abscissa!=[]:
          if data_type=='g1':
            list_of_columns.append(tab_abscissa[0]-0.5*geometry.tab_delta[0])
          else:
            list_of_columns.append(tab_abscissa[0])
        tab_strings.append('Column '+str(next_column)+': '+column_1)
        next_column += 1
        if geometry.spin_one_half and data_type=='wavefunction':
          list_of_columns.append(np.real(data[0::2]))
          tab_strings.append('Column '+str(next_column)+': '+column_2)
          next_column += 1
          list_of_columns.append(np.imag(data[0::2]))
          tab_strings.append('Column '+str(next_column)+': '+column_3)
          next_column += 1
          list_of_columns.append(np.real(data[1::2]))
          tab_strings.append('Column '+str(next_column)+': '+column_4)
          next_column += 1
          list_of_columns.append(np.imag(data[1::2]))
          tab_strings.append('Column '+str(next_column)+': '+column_5)
          next_column += 1
        else:
          list_of_columns.append(np.real(data))
          tab_strings.append('Column '+str(next_column)+': '+column_2)
          next_column += 1
          list_of_columns.append(np.imag(data))
          tab_strings.append('Column '+str(next_column)+': '+column_3)
          next_column += 1
        array_to_print=np.column_stack(list_of_columns)
      if dimension==2:
        if data_type in ['wavefunction','g1']:
          header_string=str(geometry.tab_dim[0])+' '+str(geometry.tab_delta[0])+'\n'\
                       +str(geometry.tab_dim[1])+' '+str(geometry.tab_delta[1])+'\n'\
                       +header_string
#          print(header_string)
        if data_type=='wavefunction_momentum':
          header_string=str(geometry.tab_dim[0])+' '+str(2.0*np.pi/(geometry.tab_dim[0]*geometry.tab_delta[0]))+'\n'\
                       +str(geometry.tab_dim[1])+' '+str(2.0*np.pi/(geometry.tab_dim[1]*geometry.tab_delta[1]))+'\n'\
                       +header_string
        array_to_print=data[:,:]
      if dimension==3:
        if data_type in ['wavefunction','g1']:
          header_string=str(geometry.tab_dim[0])+' '+str(geometry.tab_delta[0])+'\n'\
                       +str(geometry.tab_dim[1])+' '+str(geometry.tab_delta[1])+'\n'\
                       +str(geometry.tab_dim[2])+' '+str(geometry.tab_delta[2])+'\n'\
                       +header_string
#          print(header_string)
        if data_type=='wavefunction_momentum':
          header_string=str(geometry.tab_dim[0])+' '+str(2.0*np.pi/(geometry.tab_dim[0]*geometry.tab_delta[0]))+'\n'\
                       +str(geometry.tab_dim[1])+' '+str(2.0*np.pi/(geometry.tab_dim[1]*geometry.tab_delta[1]))+'\n'\
                       +str(geometry.tab_dim[2])+' '+str(2.0*np.pi/(geometry.tab_dim[2]*geometry.tab_delta[2]))+'\n'\
                       +header_string
        array_to_print=data[:,:,:]
    if data_type in ['autocorrelation']:
      list_of_columns.append(tab_abscissa)
      tab_strings.append('Column '+str(next_column)+': '+column_1)
      next_column += 1
      list_of_columns.append(np.real(data))
      tab_strings.append('Column '+str(next_column)+': '+column_2)
      next_column += 1
      list_of_columns.append(np.imag(data))
      tab_strings.append('Column '+str(next_column)+': '+column_3)
      next_column += 1
      array_to_print=np.column_stack(list_of_columns)
    if data_type in ['spectral_function','density_of_states','histogram_IPR','rbar','histogram_r']:
      list_of_columns.append(tab_abscissa)
      tab_strings.append('Column '+str(next_column)+': '+column_1)
      next_column += 1
      list_of_columns.append(data)
      tab_strings.append('Column '+str(next_column)+': '+column_2)
      next_column += 1
      array_to_print=np.column_stack(list_of_columns)
    if data_type in ['IPR']:
      list_of_columns.append(data)
      tab_strings.append('Column '+str(next_column)+': '+column_1)
      next_column += 1
      array_to_print=np.column_stack(list_of_columns)
    if data_type in ['lyapounov']:
      list_of_columns.append(tab_abscissa[0])
      tab_strings.append('Column '+str(next_column)+': '+column_1)
      next_column += 1
      list_of_columns.append(tab_abscissa[1])
      tab_strings.append('Column '+str(next_column)+': '+column_2)
      next_column += 1
      list_of_columns.append(data[0])
      tab_strings.append('Column '+str(next_column)+': '+column_3)
      next_column += 1
      list_of_columns.append(data[1])
      tab_strings.append('Column '+str(next_column)+': '+column_4)
      next_column += 1
      list_of_columns.append(1.0/data[0])
      tab_strings.append('Column '+str(next_column)+': '+column_5)
      next_column += 1
      list_of_columns.append(data[1]/data[0]**2)
      tab_strings.append('Column '+str(next_column)+': '+column_6)
      next_column += 1

      array_to_print=np.column_stack(list_of_columns)
 #   print(list_of_columns,len(list_of_columns))
 #   if len(list_of_columns) == 1:
 #     array_to_print = list_of_columns
 #   else:
#    print(list_of_columns)
#    array_to_print=np.column_stack(list_of_columns)
#    print(list_of_columns)
#    print(tab_strings)
    my_save_routine(file,array_to_print,header=header_string+specific_string+'\n'.join(tab_strings)+'\n')
#    np.savetxt(file,array_to_print,header=header_string+specific_string+'\n'.join(tab_strings)+'\n')
  return

def my_save_routine(file,array_to_print,header='\n'):
  dimension = array_to_print.ndim
  if dimension>3:
    print('I do not know how to print an array of dimension larger than 3')
  if dimension<3:
    np.savetxt(file,array_to_print,header=header)
  if dimension==3:
    with open(file, 'w') as outfile:
# I'm writing a header here just for the sake of readability
# Any line starting with "#" will be ignored by numpy.loadtxt
      outfile.write('# Array shape: {0}\n'.format(array_to_print.shape))
      i_header = 0
# Iterating through a ndimensional array produces slices along
# the last axis. This is equivalent to data[:,:,i] in this case
      for data_slice in array_to_print:
        if i_header==0:
          np.savetxt(outfile, data_slice,header=header+'Slice 0')

        else:
          np.savetxt(outfile, data_slice,header='Slice '+str(i_header))
        i_header+=1
  return

def output_dispersion(file,tab_data,tab_strings,general_string='Origin of data not specified'):
#  print('\n'.join(tab_strings))
  np.savetxt(file,tab_data,header=general_string+'\n'.join(tab_strings)+'\n')
  return

def print_measurements_final(measurement,initial_state=None,header_string='Origin of data not specified'):
  if (measurement.measure_potential):
#    print(measurement.potential)
    anderson.io.output_density('potential.dat',measurement.potential,measurement,header_string=header_string,tab_abscissa=measurement.grid_position,data_type='potential')
  if (measurement.measure_potential_correlation):
#    print(measurement.potential_correlation)
    anderson.io.output_density('potential_correlation.dat',measurement.potential_correlation,measurement,header_string=header_string,tab_abscissa=measurement.grid_position,data_type='potential_correlation')
  if (measurement.measure_density):
#      print(measurement.grid_position)
#    anderson.io.output_density('density_final.dat',measurement.density_final,measurement,header_string=header_string,tab_abscissa=measurement.grid_position,data_type='density')
    for i in range(measurement.tab_t_measurement_density.size):
      anderson.io.output_density('density_intermediate_'+str(i)+'.dat',measurement.density_intermediate[i],measurement,header_string=header_string+'Time = '+str(measurement.tab_t_measurement_density[i])+' \n',tab_abscissa=measurement.grid_position,data_type='density')
      if measurement.spin_one_half:
        anderson.io.output_density('density_intermediate2_'+str(i)+'.dat',measurement.density_intermediate2[i],measurement,header_string=header_string+'Time = '+str(measurement.tab_t_measurement_density[i])+' \n',tab_abscissa=measurement.grid_position,data_type='density')
  if (measurement.measure_density_momentum):
#    anderson.io.output_density('density_momentum_final.dat',measurement.density_momentum_final,measurement,header_string=header_string,tab_abscissa=measurement.frequencies,data_type='density_momentum')
    for i in range(measurement.tab_t_measurement_density.size):
      anderson.io.output_density('density_momentum_intermediate_'+str(i)+'.dat',measurement.density_momentum_intermediate[i],measurement,header_string=header_string+'Time = '+str(measurement.tab_t_measurement_density[i])+' \n',tab_abscissa=measurement.frequencies,data_type='density_momentum')
      if measurement.spin_one_half:
        anderson.io.output_density('density_momentum_intermediate2_'+str(i)+'.dat',measurement.density_momentum_intermediate2[i],measurement,header_string=header_string+'Time = '+str(measurement.tab_t_measurement_density[i])+' \n',tab_abscissa=measurement.frequencies,data_type='density_momentum')
  if (measurement.measure_wavefunction):
    anderson.io.output_density('wavefunction_initial.dat',initial_state.wfc,measurement,header_string=header_string,tab_abscissa=measurement.grid_position,data_type='wavefunction')
    anderson.io.output_density('wavefunction_final.dat',measurement.wfc,measurement,header_string=header_string,tab_abscissa=measurement.grid_position,data_type='wavefunction')
  if (measurement.measure_wavefunction_momentum):
# Ugly hack for the initial wavefunction in momentum space
    anderson.io.output_density('wavefunction_momentum_initial.dat',initial_state.convert_from_configuration_space_to_momentum_space(),measurement,header_string=header_string,tab_abscissa=measurement.frequencies,data_type='wavefunction_momentum')
    anderson.io.output_density('wavefunction_momentum_final.dat',measurement.wfc_momentum,measurement,header_string=header_string,tab_abscissa=measurement.frequencies,data_type='wavefunction_momentum')
  if (measurement.measure_autocorrelation):
    anderson.io.output_density('temporal_autocorrelation.dat',measurement.tab_autocorrelation,measurement,tab_abscissa=measurement.tab_t_measurement_dispersion,header_string=header_string,data_type='autocorrelation')
  if (measurement.measure_dispersion_position or measurement.measure_dispersion_momentum or measurement.measure_dispersion_energy):
    anderson.io.output_dispersion('dispersion.dat',measurement.tab_dispersion,measurement.tab_strings,header_string)
    if measurement.spin_one_half:
      anderson.io.output_dispersion('dispersion2.dat',measurement.tab_dispersion_2,measurement.tab_strings,header_string)
  if (measurement.measure_g1):
#    anderson.io.output_density('g1_final.dat',measurement.g1,measurement,header_string=header_string,tab_abscissa=measurement.grid_position,data_type='g1')
    for i in range(measurement.tab_t_measurement_density.size):
      anderson.io.output_density('g1_intermediate_'+str(i)+'.dat',measurement.g1_intermediate[i],measurement,header_string=header_string+'Time = '+str(measurement.tab_t_measurement_density[i])+' \n',tab_abscissa=measurement.grid_position,data_type='g1')
#    print("c'est fini")
  if measurement.measure_spectral_function:
#    print(measurement.tab_t_measurement_spectral_function.size)
#    print(measurement.tab_spectrum)
    if initial_state.type in ['point','multi_point','random']:
      base_string='density_of_states'
      data_type='density_of_states'
    else:
      base_string='spectral_function'
      data_type='spectral_function'
    if measurement.tab_t_measurement_spectral_function.size==1:
      anderson.io.output_density(base_string+'.dat',measurement.tab_spectrum, measurement,header_string=header_string,tab_abscissa=measurement.tab_energies,data_type=data_type)
    else:
#      anderson.io.output_density(base_string+'_initial.dat',measurement.tab_spectrum[:,0], measurement,header_string=header_string+'Time = '+str(measurement.tab_t_measurement_spectral_function[0])+' \n',tab_abscissa=measurement.tab_energies,data_type=data_type)
      for i in range(0,measurement.tab_t_measurement_spectral_function.size):
#        print(i)
        anderson.io.output_density(base_string+'_intermediate_'+str(i)+'.dat',measurement.tab_spectrum[:,i], measurement,header_string=header_string+'Time = '+str(measurement.tab_t_measurement_spectral_function[i])+' \n',tab_abscissa=measurement.tab_energies,data_type=data_type)
#      i=measurement.tab_t_measurement_spectral_function.size-1
#      print(i)
#      anderson.io.output_density(base_string+'_final.dat',measurement.tab_spectrum[:,i], measurement,header_string=header_string+'Time = '+str(measurement.tab_t_measurement_spectral_function[i])+' \n',tab_abscissa=measurement.tab_energies,data_type=data_type)
  return

def print_spectral_function(spectral_function,geometry,initial_state=None,header_string='Origin of data not specified'):
  if initial_state.type in ['point','multi_point','random']:
    base_string='density_of_states'
    data_type='density_of_states'
  else:
    base_string='spectral_function'
    data_type='spectral_function'
  anderson.io.output_density(base_string+'.dat',spectral_function.tab_spectrum,geometry,header_string=header_string,tab_abscissa=spectral_function.tab_energies,data_type=data_type)
  return

"""
def print_measurements_initial(measurement,initial_state,header_string='Origin of data not specified'):
  if (measurement.measure_density):
#    print(measurement.grid_position)
    anderson.io.output_density('density_initial.dat',np.abs(initial_state.wfc)**2,measurement,header_string=header_string,tab_abscissa=measurement.grid_position,data_type='density')
  if (measurement.measure_density_momentum):
    anderson.io.output_density('density_momentum_initial.dat',np.abs(initial_state.convert_to_momentum_space())**2,measurement,header_string=header_string,tab_abscissa=measurement.frequencies,data_type='density_momentum')
  if (measurement.measure_wavefunction):
    anderson.io.output_density('wavefunction_initial.dat',initial_state.wfc,measurement,header_string=header_string,tab_abscissa=measurement.grid_position,data_type='wavefunction')
  if (measurement.measure_wavefunction_momentum):
    anderson.io.output_density('wavefunction_momentum_initial.dat',initial_state.convert_to_momentum_space(),measurement,header_string=header_string,tab_abscissa=measurement.frequencies,data_type='wavefunction_momentum')
  return
"""
