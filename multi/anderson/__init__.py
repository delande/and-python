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
from . import diag, io, lyapounov, propagation

__all__ = ["diag","io","lyapounov","propagation"]

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
    self.MAX_NONLINEAR_PHASE=0.0
    self.MPI_TIME=0.0
    return

  def mpi_merge(self,comm):
    try:
      from mpi4py import MPI
    except ImportError:
      print("mpi4py is not found!")
      return
    self.GPE_TIME       = comm.reduce(self.GPE_TIME)
    self.CHE_TIME       = comm.reduce(self.CHE_TIME)
    self.EXPECT_TIME    = comm.reduce(self.EXPECT_TIME)
    self.ODE_TIME       = comm.reduce(self.ODE_TIME)
    self.TOTAL_TIME     = comm.reduce(self.TOTAL_TIME)
    self.NUMBER_OF_OPS  = comm.reduce(self.NUMBER_OF_OPS)
    self.N_SOLOUT       = comm.reduce(self.N_SOLOUT)
    self.MAX_CHE_ORDER  = comm.reduce(self.MAX_CHE_ORDER,op=MPI.MAX)
    self.DUMMY_TIME     = comm.reduce(self.DUMMY_TIME)
    self.LYAPOUNOV_TIME = comm.reduce(self.LYAPOUNOV_TIME)
    self.LYAPOUNOV_NOPS = comm.reduce(self.LYAPOUNOV_NOPS)
    self.MAX_NONLINEAR_PHASE = comm.reduce(self.MAX_NONLINEAR_PHASE,op=MPI.MAX)
    self.MPI_TIME       = comm.reduce(self.MPI_TIME)
    return


"""
The class Potential is basically a disordered potential, characterized by its dimensions
"""
class Potential:
  def __init__(self, dimension, tab_dim):
    self.dimension = dimension
    self.tab_dim = tab_dim
    self.tab_dim_cumulative = np.zeros(dimension+1,dtype=int)
    ntot = 1
    self.tab_dim_cumulative[dimension] = 1
    for i in range(dimension-1,-1,-1):
      ntot *= tab_dim[i]
      self.tab_dim_cumulative[i] = ntot
#    print(self.tab_dim_cumulative)
    self.disorder = np.zeros(tab_dim)
    return

"""
The class Hamiltonian contains all properties that define a disordered Hamiltonian discretized spatially
interaction if g for Gross-Pitaeskii
script_tunneling and script_disorder are just rescaled variables used when the temporal propagation if performed using Chebyshev polynomials
They are used in the rescaling of the Hamiltonian to bring its spectrum between -1 and +1
"""
class Hamiltonian(Potential):
  def __init__(self, dimension, tab_dim, tab_delta, tab_boundary_condition, disorder_type='anderson gaussian', correlation_length=0.0, disorder_strength=0.0, use_mkl_random=False, interaction=0.0):
    super().__init__(dimension,tab_dim)
    self.tab_delta = tab_delta
    self.disorder_strength = disorder_strength
    self.tab_tunneling = list()
    self.delta_vol = 1.0
    for i in range(dimension):
      self.tab_tunneling.append(0.5/tab_delta[i]**2)
      self.delta_vol *= tab_delta[i]
    self.tab_dim_cumulative = np.zeros(dimension+1,dtype=int)
    ntot = 1
    self.tab_dim_cumulative[dimension] = 1
    for i in range(dimension-1,-1,-1):
      ntot *= tab_dim[i]
      self.tab_dim_cumulative[i] = ntot
    self.ntot = ntot
    self.interaction = interaction
    self.tab_boundary_condition = tab_boundary_condition
    self.disorder_type = disorder_type
    self.correlation_length = correlation_length
    self.use_mkl_random = use_mkl_random
#    self.diagonal_term = np.zeros(tab_dim)
#    self.script_tunneling = 0.
#    self.script_disorder = np.zeros(tab_dim)
#    self.medium_energy = 0.
    self.generate=''
    if (disorder_type in ['anderson_gaussian','anderson_uniform','anderson_cauchy']):
      self.generate='direct'
      return
# Build mask for correlated potentials
    """
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

  """
  Generate a specific disorder configuration
  """
  def generate_disorder(self,seed):
#    print(self.use_mkl_random)
    if self.use_mkl_random:
      try:
        import mkl_random
      except ImportError:
        self.use_mkl_random=False
        print('No mkl_random found; Fallback to Numpy random')
# Here, the MKL Random Number Generator is used
# Use instead the following two lines if you prefer Numpy RNG
# np.random.seed(i)
# disorder = np.random.normal(scale=self.disorder_strength/np.sqrt(self.delta_x), size=self.dim_x)+2.0*self.tunneling
    if self.use_mkl_random:
      mkl_random.RandomState(77777, brng='SFMT19937')
      mkl_random.seed(seed,brng='SFMT19937')
      my_random_normal = mkl_random.standard_normal
      my_random_uniform = mkl_random.uniform
    else:
      np.random.seed(seed)
      my_random_normal = np.random.standard_normal
      my_random_uniform = np.random.uniform

#    print(self.tab_dim_cumulative)
    if self.disorder_type=='anderson_uniform':
      diagonal = 0.0
      multiplicative_factor = self.disorder_strength
      for i in range(self.dimension):
        diagonal += 2.0*self.tab_tunneling[i]
        multiplicative_factor /= np.sqrt(self.tab_delta[i])
      self.disorder = diagonal + multiplicative_factor*my_random_uniform(-0.5,0.5,self.ntot).reshape(self.tab_dim)
#      print(self.disorder)
      return
    if self.disorder_type=='anderson_gaussian':
      diagonal = 0.0
      multiplicative_factor = self.disorder_strength
      for i in range(self.dimension):
        diagonal += 2.0*self.tab_tunneling[i]
        multiplicative_factor /= np.sqrt(self.tab_delta[i])
#      print(diagonal,multiplicative_factor,self.ntot)
      self.disorder = diagonal + multiplicative_factor*my_random_normal(self.ntot).reshape(self.tab_dim)
#      print(self.disorder)
      return
    """
    if self.generate=='simple mask':
      self.disorder =  2.0*self.tunneling + self.disorder_strength*np.real(np.fft.ifft(self.mask*np.fft.fft(my_random_normal(self.dim_x))))
#      self.print_potential()
      return
# When a field_mask is used, the initial data is a complex uncorrelated set of Gaussian distributed random numbers in configuration space
# The Fourier transform in momentum space is also a complex uncorrelated set of Gaussian distributed random numbers
# Thus the first FT is useless and can be short circuited
    if self.generate=='field mask':
      self.disorder =  2.0*self.tunneling +0.5*self.disorder_strength*self.dim_x*np.abs(np.fft.ifft(self.mask*my_random_normal(2*self.dim_x).view(np.complex128)))**2
# Alternatively (slower)
#      self.disorder =  2.0*self.tunneling +0.5*self.disorder_strength*np.abs(np.fft.ifft(self.mask*np.fft.fft(mkl_random.standard_normal(2*self.dim_x).view(np.complex128))))**2
#      self.print_potential()
      return
    sys.exit('Disorder '+self.disorder_type+' not yet implemented!')
    return

#  def print_potential(self,filename='potential.dat'):
#    np.savetxt(filename,self.disorder-2.0*self.tunneling)
#    return
    """

  """
  Converts Hamiltonian to a full matrix for Lapack diagonalization
  """

  def generate_full_matrix(self):
    tab_index = np.zeros(self.dimension,dtype=int)
    matrix = np.diag(self.disorder.ravel())
    ntot = self.ntot
    sub_diagonal= np.zeros((2*self.dimension,ntot))
    tab_offset = np.zeros(2*self.dimension,dtype=int)
    for j in range(self.dimension):
# Offsets for the regulat hoppings
      tab_offset[j] = self.tab_dim_cumulative[j+1]
# Offsets for the periodic hoppings
      tab_offset[j+self.dimension] = self.tab_dim_cumulative[j+1]*(self.tab_dim[j]-1)
#    print(tab_offset)
    for i in range(ntot):
      index = i
      for j in range(self.dimension-1,-1,-1):
        index,tab_index[j] = divmod(index,self.tab_dim[j])
#      print(i,tab_index)
# Hopping along the various dimensions
      for j in range(self.dimension):
# Regular hopping
        if tab_index[j]<self.tab_dim[j]-1:
          sub_diagonal[j,i] = -self.tab_tunneling[j]
        else:
# Only if periodic boundary condition
          if self.tab_boundary_condition[j]=='periodic':
            sub_diagonal[j+self.dimension,i-(self.tab_dim[j]-1)*self.tab_dim_cumulative[j+1]] = -self.tab_tunneling[j]
    for j in range(self.dimension):
      np.fill_diagonal(matrix[tab_offset[j]:,:],sub_diagonal[j,:])
      np.fill_diagonal(matrix[:,tab_offset[j]:],sub_diagonal[j,:])
      if self.tab_boundary_condition[j]=='periodic':
        np.fill_diagonal(matrix[tab_offset[j+self.dimension]:,:],sub_diagonal[j+self.dimension,:])
        np.fill_diagonal(matrix[:,tab_offset[j+self.dimension]:],sub_diagonal[j+self.dimension,:])
#    print(matrix)
    return matrix
    """
    if (self.dimension==1):
      matrix = np.diag(self.disorder)
      ntot = self.tab_dim_cumulative[0]
      np.fill_diagonal(matrix[1:,:],-self.tab_tunneling[0])
      np.fill_diagonal(matrix[:,1:],-self.tab_tunneling[0])
      if self.tab_boundary_condition[0]=='periodic':
        matrix[0,ntot-1] = -self.tab_tunneling[0]
        matrix[ntot-1,0] = -self.tab_tunneling[0]
#    print(matrix)
      return matrix
    if (self.dimension==2):
    """
    """
      matrix = np.diag(self.disorder.ravel())
      ntot = self.tab_dim_cumulative[0]
      sub_diagonal= np.zeros(ntot)
      nx = self.tab_dim[0]
      ny = self.tab_dim[1]
# Hopping along x
      for i in range(0,nx-1):
        sub_diagonal[i*ny:(i+1)*ny] = -self.tab_tunneling[0]
      np.fill_diagonal(matrix[ny:,:],sub_diagonal)
      np.fill_diagonal(matrix[:,ny:],sub_diagonal)
      if self.tab_boundary_condition[0]=='periodic':
        np.fill_diagonal(matrix[ntot-ny:,:],sub_diagonal)
        np.fill_diagonal(matrix[:,ntot-ny:],sub_diagonal)
# Hopping along y
      sub_diagonal[:]=0.0
      for i in range(ny-1):
        sub_diagonal[i:ntot:ny] = -self.tab_tunneling[1]
      np.fill_diagonal(matrix[1:,:],sub_diagonal)
      np.fill_diagonal(matrix[:,1:],sub_diagonal)
      if self.tab_boundary_condition[1]=='periodic':
        sub_diagonal[:]=0.0
        sub_diagonal[0:ntot:ny] = -self.tab_tunneling[1]
        np.fill_diagonal(matrix[ny-1:,:],sub_diagonal)
        np.fill_diagonal(matrix[:,ny-1:],sub_diagonal)
#      print(matrix)
    """
    """
#      print(self.disorder.ravel())
      matrix = np.diag(self.disorder.ravel())
#      ntot = self.tab_dim_cumulative[0]
      sub_diagonal= np.zeros(self.tab_dim_cumulative[0])
# Hopping along x
      for i in range(self.tab_dim[0]-1):
        sub_diagonal[i*self.tab_dim_cumulative[1]:(i+1)*self.tab_dim_cumulative[1]] = -self.tab_tunneling[0]
      np.fill_diagonal(matrix[self.tab_dim_cumulative[1]:,:],sub_diagonal)
      np.fill_diagonal(matrix[:,self.tab_dim_cumulative[1]:],sub_diagonal)
      if self.tab_boundary_condition[0]=='periodic':
        np.fill_diagonal(matrix[self.tab_dim_cumulative[0]-self.tab_dim_cumulative[1]:,:],sub_diagonal)
        np.fill_diagonal(matrix[:,self.tab_dim_cumulative[0]-self.tab_dim_cumulative[1]:],sub_diagonal)
# Hopping along y
      sub_diagonal[:]=0.0
      for i in range(self.tab_dim_cumulative[1]-1):
        sub_diagonal[i:self.tab_dim_cumulative[0]:self.tab_dim_cumulative[1]] = -self.tab_tunneling[1]
      np.fill_diagonal(matrix[1:,:],sub_diagonal)
      np.fill_diagonal(matrix[:,1:],sub_diagonal)
      if self.tab_boundary_condition[1]=='periodic':
        sub_diagonal[:]=0.0
        sub_diagonal[0:self.tab_dim_cumulative[0]:self.tab_dim_cumulative[1]] = -self.tab_tunneling[1]
        np.fill_diagonal(matrix[self.tab_dim_cumulative[1]-1:,:],sub_diagonal)
        np.fill_diagonal(matrix[:,self.tab_dim_cumulative[1]-1:],sub_diagonal)
      print(matrix)
      return matrix
    """
    """
# loop over all indices of the big matrix
    for i in range(self.tab_dim_cumulative[0]):
# generate in tab_index the physical indices along the various directions
      index = i
      for j in range(self.dimension-1,-1,-1):
        index,tab_index[j] = divmod(index,self.tab_dim[j])
# Compute neighbors along the current direction
        if tab_index[j]<self.tab_dim[j] and tab_index[j]>0:
          neighbor = tab_index[j]+1

      print(i,tab_index)
#      matrix[i,i+1] = -self.tunneling
#      matrix[i+1,i] = -self.tunneling
#    if self.boundary_condition=='periodic':
#      matrix[0,n-1] = -self.tunneling
#      matrix[n-1,0] = -self.tunneling
#    print(matrix)
    return matrix
    """

  def generate_full_complex_matrix(self,pivot):
    matrix = self.generate_full_matrix().astype(np.complex128)
    np.fill_diagonal(matrix,matrix.diagonal()-pivot)
    return matrix

  """
  Converts Hamiltonian to a sparse matrix for sparse diagonalization
  """
  def generate_sparse_matrix(self):
    tab_index = np.zeros(self.dimension,dtype=int)
    diagonal = self.disorder.ravel()
    ntot = self.ntot
    sub_diagonal= np.zeros((2*self.dimension,ntot))
    tab_offset = np.zeros(2*self.dimension,dtype=int)
    for j in range(self.dimension):
# Offsets for the regulat hoppings
      tab_offset[j] = self.tab_dim_cumulative[j+1]
# Offsets for the periodic hoppings
      tab_offset[j+self.dimension] = self.tab_dim_cumulative[j+1]*(self.tab_dim[j]-1)
#    print(tab_offset)
    for i in range(ntot):
      index = i
      for j in range(self.dimension-1,-1,-1):
        index,tab_index[j] = divmod(index,self.tab_dim[j])
#      print(i,tab_index)
# Hopping along the various dimensions
      for j in range(self.dimension):
# Regular hopping
        if tab_index[j]<self.tab_dim[j]-1:
          sub_diagonal[j,i] = -self.tab_tunneling[j]
        else:
# Only if periodic boundary condition
          if self.tab_boundary_condition[j]=='periodic':
            sub_diagonal[j+self.dimension,i-(self.tab_dim[j]-1)*self.tab_dim_cumulative[j+1]] = -self.tab_tunneling[j]
    diagonals = [diagonal]
    offsets = [0]
    for j in range(self.dimension):
      diagonals.extend([sub_diagonal[j,:],sub_diagonal[j,:]])
      offsets.extend([tab_offset[j],-tab_offset[j]])
      if self.tab_boundary_condition[j]=='periodic':
        diagonals.extend([sub_diagonal[j+self.dimension,:],sub_diagonal[j+self.dimension,:]])
        offsets.extend([tab_offset[j+self.dimension],-tab_offset[j+self.dimension]])
#    print(diagonals)
#    print(offsets)
    self.sparse_matrix = ssparse.diags(diagonals,offsets,format='csr')
#    print('Sparse matrix computed')
#    print(matrix.toarray())
    return

  """
  Converts Hamiltonian to a complex sparse matrix for sparse diagonalization
  """
  def generate_sparse_complex_matrix(self,pivot):
    matrix = self.generate_sparse_matrix().astype(np.complex128)
    matrix.setdiag(matrix.diagonal()-pivot)
#    print(matrix.toarray())
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
      e_max_0=0.0
      for i in range(self.dimension):
        e_max_0 += 2.0/(self.tab_delta[i]**2)

      n_iterations_hamiltonian_bounds=min(10,int(50./np.log10(e_max_0)))
  # rough estimate of the minimum energy (no disorder taken into account)
      e_min_0 = 0.0
  # First determine the lower bound
  # Start with plane wave k=0 (minimum energy state)
      psic = Wavefunction(self.tab_dim, self.tab_delta)
      psic.plane_wave(0.0)
  #    psic2 = np.empty(self.dim_x,dtype=np.complex128)
      finished = False
      estimated_bound = 0.0
      while not finished:
        for i in range(n_iterations_hamiltonian_bounds-1):
          psic.wfc = self.apply_h(psic.wfc)-e_max_0*psic.wfc
        norm = np.linalg.norm(psic.wfc)**2*self.delta_vol
        psic.wfc = self.apply_h(psic.wfc)-e_max_0*psic.wfc
        new_norm = np.linalg.norm(psic.wfc)**2*self.delta_vol
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
      tab_k= []
      for i in range(self.dimension):
        tab_k.append(np.pi/self.tab_delta[i])
      psic.plane_wave(tab_k)
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
      e_max_0=0.0
      for i in range(self.dimension):
        e_max_0 += 1.0/(self.tab_delta[i]**2)
      e_min=np.amin(self.disorder)-e_max_0
      e_max=np.amax(self.disorder)+e_max_0
#    print(e_min,e_max)
    self.e_min = e_min
    self.e_max = e_max
    self.medium_energy = 0.5*(e_max+e_min)
    self.two_over_delta_e = 2.0/(e_max-e_min)
    self.two_e0_over_delta_e = self.medium_energy*self.two_over_delta_e
    return
  """
  Computes the rescaling of Hamiltonian for the Chebyshev method
  """
  def script_h(self,e_min,e_max):
    one_over_delta_e = 1.0/(e_max-e_min)
    #script_tunneling = 2.0*self.tunneling*one_over_delta_e
    #script_disorder = (2.0*self.disorder-(e_min+e_max))*one_over_delta_e
    self.two_over_delta_e = 2.0*one_over_delta_e
    self.two_e0_over_delta_e = (e_min+e_max)*one_over_delta_e
#  print(script_tunneling,script_disorder[0:10])
    #return script_tunneling, script_disorder
    return

class Wavefunction:
  def __init__(self, tab_dim, tab_delta):
    self.tab_dim = tab_dim
    self.tab_delta = tab_delta
    self.wfc = np.zeros(tab_dim,dtype=np.complex128)
#    dim_max = max(tab_dim)
    dimension = len(tab_dim)
#    self.tab_position = np.zeros((dimension,dim_max))
    self.tab_position = list()
    self.delta_vol = 1.0
    for i in range(dimension):
      self.delta_vol *= tab_delta[i]
      self.tab_position.append(0.5*tab_delta[i]*np.arange(1-tab_dim[i],tab_dim[i]+1,2))
    self.tab_dim_cumulative = np.zeros(dimension+1,dtype=int)
    ntot = 1
    self.tab_dim_cumulative[dimension] = 1
    for i in range(dimension-1,-1,-1):
      ntot *= tab_dim[i]
      self.tab_dim_cumulative[i] = ntot
    self.ntot=ntot
#    print(self.tab_position)
    return

  def gaussian(self,tab_k_0,tab_sigma_0):
    self.tab_k_0 = tab_k_0
    self.tab_sigma_0 = tab_sigma_0
    tab_position = np.meshgrid(*self.tab_position,indexing='ij')
    tab_phase = np.zeros(self.tab_dim)
    tab_amplitude = np.zeros(self.tab_dim)
    for i in range(len(tab_position)):
      tab_phase += self.tab_k_0[i]*tab_position[i]
      tab_amplitude += (tab_position[i]/self.tab_sigma_0[i])**2
# The next two lines are to avoid too small values of abs(psi[i])
# which slow down the calculation
    threshold = 100.
    tab_amplitude =np.where(tab_amplitude>threshold,threshold,tab_amplitude)
    psi = np.exp(-0.5*tab_amplitude+1j*tab_phase)
    self.wfc = psi/(np.linalg.norm(psi)*np.sqrt(self.delta_vol))
    return

  def plane_wave(self,tab_k_0):
#    self.type = 'Plane wave'
    self.tab_k_0 = tab_k_0
    tab_position = np.meshgrid(*self.tab_position,indexing='ij')
    tab_phase = np.zeros(self.tab_dim)
    for i in range(len(tab_position)):
      tab_phase += self.tab_k_0[i]*tab_position[i]
    self.wfc = np.exp(1j*tab_phase)/np.sqrt(self.ntot*self.delta_vol)
    return

  def overlap(self, other_wavefunction):
#    return np.sum(self.wfc*np.conj(other_wavefunction.wfc))*self.delta_x
# The following line is 5 times faster!
    return np.vdot(self.wfc,other_wavefunction.wfc)*self.delta_vol

  def expectation_value_local_operator(self, local_operator):
#    density = np.abs(self.wfc)**2
#   norm = np.sum(density)
#    x = np.sum(density*local_operator)
#    return np.sum(density*local_operator)/np.sum(density)
    return (np.vdot(self.wfc,local_operator*self.wfc)/np.vdot(self.wfc,self.wfc)).real
 #   return np.vdot(self.wfc,local_operator*self.wfc).real*self.delta_x
#    return x/norm

  def convert_to_momentum_space(self,use_mkl_fft=True):
#    psic_momentum = self.delta_x*np.fft.fft(self.wfc)/np.sqrt(2.0*np.pi)
#   psic_momentum *= np.exp(-1j*np.arange(self.dim_x)*np.pi*(1.0/self.dim_x-1.0))
#    return np.fft.fftshift(self.delta_x*np.fft.fft(self.wfc)*np.exp(-1j*np.arange(self.dim_x)*np.pi*(1.0/self.dim_x-1.0))/np.sqrt(2.0*np.pi))
# The conversion space->momentum is a bit tricky, here are the explanations:
# Position x_i is discretized as x_k=(k+1/2-dim_x/2)delta_x for 0\leq k \lt dim_x
# Momentum is discretized as p_l = l delta_p for 0 \leq l \lt dim_x and delta_p=2\pi/(dim_x*delta_x)
# (more on negative momenta below)
# The position->momentum transformation is defined by \psi(p) = 1/\sqrt{2\pi} \int_0^L \psi(x) \exp(-ipx) dx
# where L=dim_x*delta_x is the system size.
# An elementary calculation shows that, after discretization:
# \psi(p_l) = delta_x/\sqrt{2\pi} \exp(-i\pi l(1/dim_x-1)) \sum_{k=0..dim_x-1} \psi(x_k) \exp{-2i\pi kl/dim_x}
# The last sum is directly given by the routine np.fft.fft (or mkl_fft.fft) applied on self.wfc
# After that, remains the multiplication by delta_x/\sqrt{2\pi} \exp(-i\pi l(1/dim_x-1))
# Because of FFT, the momentum is also periodic, meaning that the l values above are not 0..dim_x-1, but rather
# -dim_x/2..dim_x/2-1. At the exist of np.fft.fft, they are in the order 0,1,...dim_x/2-1,-dim_x/2,..,-1.
# They are put back in the natural orde -dim_x/2...dim_x/2-1 using he np.fft.fftshift routine.
    if use_mkl_fft:
      try:
        import mkl_fft
        my_fft = mkl_fft.fftn
      except ImportError:
        my_fft = np.fft.fftn
    else:
       my_fft = np.fft.fftn
    return np.fft.fftshift(self.delta_vol*my_fft(self.wfc))
#    return np.fft.fftshift(self.delta_x*my_fft(self.wfc)*np.exp(-1j*np.arange(self.dim_x)*np.pi*(1.0/self.dim_x-1.0))/np.sqrt(2.0*np.pi))

  def expectation_value_local_momentum_operator(self, local_operator):
#    density = np.abs(self.wfc_momentum)**2
#    norm = np.sum(density)
#    x = np.sum(density*local_operator)
#    print(norm,x)
#    return x/norm
#    return np.sum(density*local_operator)/np.sum(density)
    return (np.vdot(self.wfc_momentum,local_operator*self.wfc_momentum)/np.vdot(self.wfc_momentum,self.wfc_momentum)).real

  def energy(self, H):
#    rhs = H.apply_h(self.wfc)
    non_linear_energy = 0.5*H.interaction*np.sum(np.abs(self.wfc)**4)*self.delta_vol
    energy = np.sum(np.real(self.wfc*np.conjugate(H.apply_h(self.wfc))))*self.delta_vol + non_linear_energy
    norm = np.linalg.norm(self.wfc)**2*self.delta_vol
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



