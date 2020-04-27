#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Aug 16 17:05:10 2019

@author: delande

"""

import os
import sys
import math
import numpy as np
import scipy.sparse as ssparse
import mkl_random

#__all__ = ["diag","lyapounov","propagation"]

class Timing:
  def __init__(self):
    self.GPE_TIME=0.0
    self.CHE_TIME=0.0
    self.EXPECT_TIME=0.0
    self.ODE_TIME=0.0
    self.TOTAL_TIME=0.0
    self.NUMBER_OF_OPS=0.0
    self.N_SOLOUT=0
    self.MAX_CHE_ORDER=0
    self.DUMMY_TIME=0.0
    self.LYAPOUNOV_TIME=0.0
    self.LYAPOUNOV_NOPS=0
    return 
    
"""
The class Potential is basically a 1D disordered potential, characterized by its length and the disorder strength
"""
class Potential:
  def __init__(self, dim_x):
    self.dim_x = dim_x
    self.disorder = np.zeros(dim_x)
    return

"""
The class Hamiltonian contains all properties that define a disordered Hamiltonian discretized spatially
interaction if g for Gross-Pitaeskii
script_tunneling and script_disorder are just rescaled variables used when the temporal propagation if performed using Chebyshev polynomials
They are used in the rescaling of the Hamiltonian to bring its spectrum between -1 and +1
"""  
class Hamiltonian(Potential):
  def __init__(self, dim_x, delta_x, boundary_condition='periodic', disorder_type='anderson gaussian', correlation_length=0.0, disorder_strength=0.0, interaction=0.0):
    super().__init__(dim_x)
    self.delta_x = delta_x
    self.disorder_strength = disorder_strength
    self.tunneling = 0.5/delta_x**2
    self.interaction = interaction
    self.boundary_condition = boundary_condition
    self.disorder_type = disorder_type
    self.correlation_length = correlation_length
    self.diagonal_term = np.zeros(dim_x)
    self.script_tunneling = 0.
    self.script_disorder = np.zeros(dim_x)
    self.medium_energy = 0.
    self.generate=''
    if (disorder_type in ['anderson_gaussian','anderson_uniform','anderson_cauchy']):
      self.generate='direct'
      return
# Build mask for correlated potentials
    if disorder_type=='regensburg':
      self.generate = 'simple mask'
      self.mask = np.zeros(dim_x)
      inv_k_length = 2.0*np.pi*self.correlation_length/(self.dim_x*self.delta_x)
      if inv_k_length<20./dim_x:
        mask_size = dim_x//2+1
      else:
        mask_size = int(10.0/inv_k_length+1.5)
#      self.mask = np.zeros(dim_x)
      self.mask[0:mask_size] = np.exp(-0.25*(np.arange(mask_size)*inv_k_length)**2)
      self.mask[dim_x-mask_size+1:dim_x]=self.mask[mask_size-1:0:-1]
      self.mask*=np.sqrt(dim_x/np.sum(self.mask**2))
      return
    if disorder_type=='singapore':
      self.generate = 'simple mask'
      self.mask = np.zeros(dim_x)
      inv_k_length = 2.0*np.pi*self.correlation_length/(self.dim_x*self.delta_x)
      if inv_k_length<2.0/dim_x:
        mask_size = dim_x//2+1
      else:
        mask_size = int(1.0/inv_k_length+0.5)
#      self.mask = np.zeros(dim_x)
      self.mask[0:mask_size] = np.ones(mask_size)
      self.mask[dim_x-mask_size+1:dim_x]=self.mask[mask_size-1:0:-1]
      self.mask*=np.sqrt(dim_x/np.sum(self.mask**2))
      return
    if disorder_type=='speckle':
      self.generate = 'field mask'
      self.mask = np.zeros(dim_x)
      inv_k_length = 2.0*np.pi*self.correlation_length/(self.dim_x*self.delta_x)
      if inv_k_length<2.0/dim_x:
        mask_size = dim_x//2+1
      else:
        mask_size = int(1.0/inv_k_length+0.5)
#      self.mask = np.zeros(dim_x)
      self.mask[0:mask_size] = np.ones(mask_size)
      self.mask[dim_x-mask_size+1:dim_x]=self.mask[mask_size-1:0:-1]
      self.mask*=np.sqrt(dim_x/np.sum(self.mask**2))
      return
#      print(dim_x,mask_size)
#      print(self.mask)
#      self.mask[0]=dim_x        
    if disorder_type=='konstanz':
      self.generate = 'field mask'
      self.mask = np.zeros(dim_x)
      inv_k_length = 2.0*np.pi*self.correlation_length/(self.dim_x*self.delta_x)
      if inv_k_length<20./dim_x:
        mask_size = dim_x//2+1
      else:
        mask_size = int(10.0/inv_k_length+1.5)
#      self.mask = np.zeros(dim_x)
      self.mask[0:mask_size] = np.exp(-0.5*(np.arange(mask_size)*inv_k_length)**2)
      self.mask[dim_x-mask_size+1:dim_x]=self.mask[mask_size-1:0:-1]
      self.mask*=np.sqrt(dim_x/np.sum(self.mask**2))
      return
    return

  """
  Generate a specific disorder configuration
  """    
  def generate_disorder(self,seed):
# Here, the MKL Random Number Generator is used
# Use instead the following two lines if you prefer Numpy RNG     
# np.random.seed(i)
# disorder = np.random.normal(scale=self.disorder_strength/np.sqrt(self.delta_x), size=self.dim_x)+2.0*self.tunneling
    mkl_random.RandomState(77777, brng='SFMT19937')
    mkl_random.seed(seed,brng='SFMT19937')
    if self.disorder_type=='anderson_gaussian':
      self.disorder = 2.0*self.tunneling + (self.disorder_strength/np.sqrt(self.delta_x))*mkl_random.standard_normal(self.dim_x)
      return
    if self.generate=='simple mask':
      self.disorder =  2.0*self.tunneling + self.disorder_strength*np.real(np.fft.ifft(self.mask*np.fft.fft(mkl_random.standard_normal(self.dim_x))))
#      self.print_potential()
      return
# When a field_mask is used, the initial data is a complex uncorrelated set of Gaussian distributed random numbers in configuration space
# The Fourier transform in momentum space is also a complex uncorrelated set of Gaussian distributed random numbers
# Thus the first FT is useless and can be short circuited      
    if self.generate=='field mask':
      self.disorder =  2.0*self.tunneling +0.5*self.disorder_strength*self.dim_x*np.abs(np.fft.ifft(self.mask*mkl_random.standard_normal(2*self.dim_x).view(np.complex128)))**2
# Alternatively (slower)
#      self.disorder =  2.0*self.tunneling +0.5*self.disorder_strength*np.abs(np.fft.ifft(self.mask*np.fft.fft(mkl_random.standard_normal(2*self.dim_x).view(np.complex128))))**2
#      self.print_potential()
      return
    sys.exit('Disorder '+self.disorder_type+' not yet implemented!')
    return

  def print_potential(self):
    np.savetxt('potential.dat',self.disorder-2.0*self.tunneling)
    return
  
  """
  Converts Hamiltonian to a full matrix for Lapack diagonalization
  """
  
  def generate_full_matrix(self):
    n = self.dim_x
    matrix = np.diag(self.disorder)
    for i in range(n-1):
      matrix[i,i+1] = -self.tunneling
      matrix[i+1,i] = -self.tunneling
    if self.boundary_condition=='periodic': 
      matrix[0,n-1] = -self.tunneling
      matrix[n-1,0] = -self.tunneling
#    print(matrix)
    return matrix
  
  """
  Converts Hamiltonian to a sparse matrix for sparse diagonalization
  """
  def generate_sparse_matrix(self):
    n = self.dim_x
    if self.boundary_condition=='periodic':    
      diagonals=[self.disorder,np.full(n-1,-self.tunneling),np.full(n-1,-self.tunneling),[-self.tunneling],[-self.tunneling]]
      matrix = ssparse.diags(diagonals,[0,-1,1,1-n,n-1],format='csr')
    else:  
      diagonals=[self.disorder,np.full(n-1,-self.tunneling),np.full(n-1,-self.tunneling)]
      matrix = ssparse.diags(diagonals,[0,-1,1],format='csr')  
#    print(matrix)
    return matrix
  
  """
  Apply Hamiltonian on a wavefunction
  """
  def apply_h(self, wfc):
    dim_x = self.dim_x
    rhs = np.empty(dim_x,dtype=np.complex128)
    if self.boundary_condition=='periodic': 
      rhs[0]       = -self.tunneling * (wfc[dim_x-1] + wfc[1]) + self.disorder[0] * wfc[0]
      rhs[dim_x-1] = -self.tunneling * (wfc[dim_x-2] + wfc[0]) + self.disorder[dim_x-1] * wfc[dim_x-1]
    else:    
      rhs[0]       = -self.tunneling * wfc[1]       + self.disorder[0]       * wfc[0]
      rhs[dim_x-1] = -self.tunneling * wfc[dim_x-2] + self.disorder[dim_x-1] * wfc[dim_x-1]
    rhs[1:dim_x-1] = -self.tunneling * (wfc[0:dim_x-2] + wfc[2:dim_x]) + self.disorder[1:dim_x-1] * wfc[1:dim_x-1]
    return rhs  

  """
  Try to estimate bounds of the spectrum of The Hamiltonian
  This is needed for the temporal propagation using the Chebyshev method
  """
  def energy_range(self, accurate=False):
# The accurate determination should be used for starong disorder    
    if (accurate):
  # rough estimate of the maximum energy (no disorder taken into account)
      e_max_0 = 2.0/(self.delta_x**2)
      n_iterations_hamiltonian_bounds=min(10,int(50./np.log10(e_max_0)))
  # rough estimate of the minimum energy (no disorder taken into account) 
      e_min_0 = 0.0
  # First determine the lower bound
  # Start with plane wave k=0 (minimum energy state)
      psic = Wavefunction(self.dim_x, self.delta_x)
      psic.plane_wave(0.0)
  #    psic2 = np.empty(self.dim_x,dtype=np.complex128)
      finished = False
      estimated_bound = 0.0
      while not finished:
        for i in range(n_iterations_hamiltonian_bounds-1):
          psic.wfc = self.apply_h(psic.wfc)-e_max_0*psic.wfc
        norm = np.linalg.norm(psic.wfc)**2*self.delta_x
        psic.wfc = self.apply_h(psic.wfc)-e_max_0*psic.wfc
        new_norm = np.linalg.norm(psic.wfc)**2*self.delta_x
        new_estimated_bound = np.sqrt(new_norm/norm)
        norm = new_norm
        if (norm>1.e100):
          psic.wfc *= 1.0/np.sqrt(norm)
          norm = 1.0
  #    print(norm,new_estimated_bound)
        if (new_estimated_bound < 1.0001*estimated_bound):
          finished = True
        estimated_bound=new_estimated_bound
      e_max = e_min_0 + 1.01 * estimated_bound
  # Then determine the lower bound
  # Start with plane wave k=pi (maximum energy state)
      psic.plane_wave(np.pi/self.delta_x)
      finished = False
      estimated_bound = 0.0
      while not finished:
        for i in range(n_iterations_hamiltonian_bounds-1):
          psic.wfc = self.apply_h(psic.wfc)-e_min_0*psic.wfc
        norm = np.linalg.norm(psic.wfc)**2*self.delta_x
        psic.wfc = self.apply_h(psic.wfc)-e_min_0*psic.wfc
        new_norm = np.linalg.norm(psic.wfc)**2*self.delta_x
        new_estimated_bound = np.sqrt(new_norm/norm)
        norm = new_norm
        if (norm>1.e100):
          psic.wfc *= 1.0/np.sqrt(norm)
          norm = 1.0
  #    print(norm,new_estimated_bound)
        if (new_estimated_bound < 1.0001*estimated_bound):
          finished = True
        estimated_bound=new_estimated_bound
      e_min = e_max_0 - 1.01 * estimated_bound
    else:
# Very basic bounds using the min/max of the potential       
      e_min=np.amin(self.disorder)-1.0/(self.delta_x**2)
      e_max=np.amax(self.disorder)+1.0/(self.delta_x**2)
#    print(e_min,e_max)
    return e_min,e_max

  """
  Computes the rescaling of Hamiltonian for the Chebyshev method
  """  
  def script_h(self,e_min,e_max):
    one_over_delta_e = 1.0/(e_max-e_min)
    script_tunneling = 2.0*self.tunneling*one_over_delta_e
    script_disorder = (2.0*self.disorder-(e_min+e_max))*one_over_delta_e
#  print(script_tunneling,script_disorder[0:10])
    return script_tunneling, script_disorder
  
class Wavefunction:
  def __init__(self, dim_x, delta_x):
    self.dim_x = dim_x
    self.delta_x = delta_x
    self.wfc = np.zeros(dim_x,dtype=np.complex128)
    self.position = 0.5*delta_x*np.arange(1-dim_x,dim_x+1,2)
    return
    
  def gaussian(self,sigma_0,k_0):
    psi=np.exp(1j*k_0*self.position-0.5*(self.position/sigma_0)**2)
#    self.type = 'Gaussian wavepacket'
    self.k_0 = k_0
    self.sigma_0 = sigma_0
    self.wfc = psi/(np.linalg.norm(psi)*np.sqrt(self.delta_x))
    return
  
  def plane_wave(self,k_0):
#    self.type = 'Plane wave'
    self.k_0 = k_0
    self.sigma_0 = 0.0
    self.wfc = np.exp(1j*k_0*self.position)/np.sqrt(self.dim_x*self.delta_x) 
    return

  def overlap(self, other_wavefunction):
#    return np.sum(self.wfc*np.conj(other_wavefunction.wfc))*self.delta_x
# The following line is 5 times faster!
    return np.vdot(self.wfc,other_wavefunction.wfc)*self.delta_x 

  def expectation_value_local_operator(self, local_operator):
    density = np.abs(self.wfc)**2
    norm = np.sum(density)
    x = np.sum(density*local_operator)
    return x/norm  

  def convert_to_momentum_space(self):
#    psic_momentum = self.delta_x*np.fft.fft(self.wfc)/np.sqrt(2.0*np.pi)
 #   psic_momentum *= np.exp(-1j*np.arange(self.dim_x)*np.pi*(1.0/self.dim_x-1.0))
    return np.fft.fftshift(self.delta_x*np.fft.fft(self.wfc)*np.exp(-1j*np.arange(self.dim_x)*np.pi*(1.0/self.dim_x-1.0))/np.sqrt(2.0*np.pi))
  
  def expectation_value_local_momentum_operator(self, local_operator):
    density = np.abs(self.wfc_momentum)**2
    norm = np.sum(density)
    x = np.sum(density*local_operator)
    return x/norm    

  def energy(self, H):
#    rhs = H.apply_h(self.wfc)
    non_linear_energy = 0.5*H.interaction*np.sum(np.abs(self.wfc)**4)*self.delta_x
    energy = np.sum(np.real(self.wfc*np.conjugate(H.apply_h(self.wfc))))*self.delta_x + non_linear_energy  
    norm = np.linalg.norm(self.wfc)**2*self.delta_x
#  print('norm=',norm,energy,non_linear_energy)
    return energy/norm,non_linear_energy/norm
  
#def expectation_value_local_operator(wfc, local_operator):
#  density = np.abs(wfc)**2
#  norm = np.sum(density)
#  x = np.sum(density*local_operator)
#  return x/norm    
    
def compute_correlation(x,y):
  return np.fft.ifft(np.fft.fft(x)*np.conj(np.fft.fft(y)))/x.size 
  
def determine_unique_postfix(fn):
  if not os.path.exists(fn):
    return ''
  path, name = os.path.split(fn)
  name, ext = os.path.splitext(name)
  make_fn = lambda i: os.path.join(path, '%s_%d%s' % (name, i, ext))
  i = 0
  while True:
    i = i+1  
    uni_fn = make_fn(i)
    if not os.path.exists(uni_fn):
      return '_'+str(i)



