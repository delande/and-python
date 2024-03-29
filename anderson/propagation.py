#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Dec 12 16:33:12 2019

@author: delande
"""

import math
import numpy as np
from scipy.integrate import ode
import scipy.special as sp
import timeit
import anderson
import copy
import sys

def numba_decorator(x):
  try:
    import numba
    return numba.jit(nopython=True,fastmath=True,cache=True)(x)
  except:
    print('numba package not found, this will use the slower regular Python version')
    return(x)
  pass

from anderson.wavefunction import Wavefunction

class Temporal_Propagation:
  def __init__(self, t_max, delta_t, method='che', accuracy=1.e-6, accurate_bounds=False, data_layout='real', want_ctypes=True, H=None):
    self.t_max = t_max
    self.method = method
    self.want_ctypes = want_ctypes
    self.use_ctypes = want_ctypes
    self.data_layout = data_layout
    self.delta_t = delta_t
    self.script_delta_t = 0.
    self.accuracy = accuracy
    self.accurate_bounds = accurate_bounds
# Is there a full specific Chebyshev implementation?
    self.has_specific_full_chebyshev_routine = False
    if not H.spin_one_half and self.want_ctypes:
      try:
        import ctypes
        import numpy.ctypeslib as ctl
        self.has_specific_full_chebyshev_routine = True
        self.chebyshev_ctypes_lib=ctypes.CDLL(anderson.__path__[0]+"/ctypes/chebyshev.so")
        if self.data_layout=='real':
          self.chebyshev_ctypes_lib.chebyshev_real.argtypes = [ctypes.c_int, ctl.ndpointer(np.intc), ctypes.c_int, ctl.ndpointer(np.intc),\
            ctl.ndpointer(np.float64), ctl.ndpointer(np.float64), ctl.ndpointer(np.float64), ctl.ndpointer(np.float64), ctl.ndpointer(np.float64), ctl.ndpointer(np.float64),\
            ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double]
          self.chebyshev_ctypes_lib.chebyshev_real.restype = ctypes.c_double
          if not (hasattr(self.chebyshev_ctypes_lib,'chebyshev_real') and    hasattr(self.chebyshev_ctypes_lib,'elementary_clenshaw_step_real_'+str(H.dimension)+'d')):
            self.has_specific_full_chebyshev_routine = False
            self.chebyshev_ctypes_lib = None
            if H.seed == 0 :
              print("\nWarning, chebyshev C library found, but without routine for real data layout and dimension "+str(H.dimension)+", this uses the slow Python version\n")
        if self.data_layout=='complex':
          self.chebyshev_ctypes_lib.chebyshev_complex.argtypes = [ctypes.c_int, ctl.ndpointer(np.intc), ctypes.c_int, ctl.ndpointer(np.intc),\
            ctl.ndpointer(np.complex128), ctl.ndpointer(np.complex128), ctl.ndpointer(np.complex128), ctl.ndpointer(np.float64), ctl.ndpointer(np.float64), ctl.ndpointer(np.float64),\
            ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double]
          self.chebyshev_ctypes_lib.chebyshev_complex.restype = ctypes.c_double
          if not (hasattr(self.chebyshev_ctypes_lib,'chebyshev_real') and    hasattr(self.chebyshev_ctypes_lib,'elementary_clenshaw_step_complex_'+str(H.dimension)+'d')):
            self.has_specific_full_chebyshev_routine = False
            self.chebyshev_ctypes_lib = None
            if H.seed == 0 :
              print("\nWarning, chebyshev C library found, but without routine for complex data layout and dimension "+str(H.dimension)+", this uses the slow Python version\n")
      except:
        self.has_specific_full_chebyshev_routine = False
        self.chebyshev_ctypes_lib = None
        if H.seed == 0 :
          print("\nWarning, no ctypes module, no numpy.ctypeslib module or no chebyshev C library found, this uses the slow Python version!\n")
    self.use_ctypes = self.has_specific_full_chebyshev_routine and self.want_ctypes
    if self.use_ctypes:
      self.chebyshev_propagation = chebyshev_propagation_ctypes
    else:
      self.chebyshev_propagation = chebyshev_propagation_generic
 # Is there a specific routine for a Chebyshev step?
# In general, there is no specific routine
    self.has_specific_chebyshev_step_routine = False
    self.chebyshev_step = eval("chebyshev_step_generic_"+self.data_layout)
# There are few specific cases for a specialized routine is available
# Standard 1d system
    if H.dimension == 1 and not H.spin_one_half:
      self.has_specific_chebyshev_step_routine = True
      self.chebyshev_step = eval("chebyshev_step_1d_"+self.data_layout)
# Standard 2d system
    if H.dimension == 2 and not H.spin_one_half:
      self.has_specific_chebyshev_step_routine = True
      self.chebyshev_step = eval("chebyshev_step_2d_"+self.data_layout)
# Standard 3d system
    if H.dimension == 3 and not H.spin_one_half:
      self.has_specific_chebyshev_step_routine = True
      self.chebyshev_step = eval("chebyshev_step_3d_"+self.data_layout)
    return

  def compute_chebyshev_coefficients(self,accuracy,timing):
    assert self.script_delta_t!=0.,"Rescaled time step for Chebyshev propagation is zero!"
    i = int(2.0*self.script_delta_t)+10
    while (abs(sp.jv(i,self.script_delta_t))<accuracy or i==0):
      i -= 1
# max order must be an even number
    max_order = 2*((i+1)//2)
    if (max_order>timing.MAX_CHE_ORDER):
      timing.MAX_CHE_ORDER=max_order
#  print(max_order)
#  tab_coef=np.zeros(max_order+1)
    z=np.arange(max_order+1)
    self.tab_coef=-4.0*sp.jv(z,-self.script_delta_t)*(((z%4)>1)-0.5)
    self.tab_coef[0] *=  0.5
    self.accuracy = accuracy
# The three previous lines are equivalent to the following loop
#  tab_coef=np.zeros(max_order+1)
#  for order in range(1,max_order):
#    tab_coef[order] = -4.0*sp.jv(order,-delta_t)*(((order%4)>1)-0.5)
# The following uses mpmath but is awfully slow
#   tab_coef[order] = -4.0*mpmath.besselj(order,-delta_t)*(((order%4)>1)-0.5)
#  tab_coef[0] = sp.jv(0,-delta_t)
    return


def chebyshev_step_generic_complex(wfc, H, psi, psi_old, c_coef, add_real, c1, c2, tab_c3):
#  print('using chebyshev_step_generic_complex')
#  print('wfc',wfc.shape,wfc.dtype)
#  print('psi',psi.shape,psi.dtype)
#  print('psi_old',psi_old.shape,psi_old.dtype)
#  print('disorder',H.disorder.shape)
#  print('in',wfc[0],psi[0],psi_old[0],c_coef,one_or_two,add_real)
#  print("inside chebyshev_step_generic_complex")
  if not(add_real):
    c_coef*=1j
# Generic code uses the sparse multiplication
  psi_old[:] = c1*H.apply_h(psi)-c2*psi[:]+c_coef*wfc[:]-psi_old[:]
#  print('psi',psi)
#  print('psi_old',psi_old)
  return

def chebyshev_step_generic_real(wfc, H, psi, psi_old, c_coef, add_real, c1, c2, tab_c3):
#  print('wfc',wfc.shape,wfc.dtype)
#  print('psi',psi.shape,psi.dtype)
#  print('psi_old',psi_old.shape,psi_old.dtype)
#  print('in',wfc[0],psi[0],psi_old[0],c_coef,one_or_two,add_real)
  ntot = H.hs_dim
  if add_real:
    psi_old[0:ntot] = c1*H.apply_h(psi[0:ntot])-c2*psi[0:ntot]+c_coef*wfc[0:ntot]-psi_old[0:ntot]
    psi_old[ntot:2*ntot] = c1*H.apply_h(psi[ntot:2*ntot])-c2*psi[ntot:2*ntot]+c_coef*wfc[ntot:2*ntot]-psi_old[ntot:2*ntot]
  else:
    psi_old[0:ntot] = c1*H.apply_h(psi[0:ntot])-c2*psi[0:ntot]-c_coef*wfc[ntot:2*ntot]-psi_old[0:ntot]
    psi_old[ntot:2*ntot] = c1*H.apply_h(psi[ntot:2*ntot])-c2*psi[ntot:2*ntot]+c_coef*wfc[0:ntot]-psi_old[ntot:2*ntot]
  return

"""
def chebyshev_step_1d_complex(wfc, H, psi, psi_old, c_coef, add_real, c1, c2, tab_c3):
#  print('wfc',wfc.shape,wfc.dtype)
#  print('psi',psi.shape,psi.dtype)
#  print('psi_old',psi_old.shape,psi_old.dtype)
#  print('disorder',H.disorder.shape)
#  print('in',wfc[0],psi[0],psi_old[0],c_coef,one_or_two,add_real)
  if not(add_real):
    c_coef*=1j
  c3=tab_c3[0]
  dim_x = H.tab_dim[0]
  if H.tab_boundary_condition[0]=='periodic':
    psi_old[0]       = (c1*H.disorder[0]-c2)      *psi[0]      -c3*(psi[1]+psi[dim_x-1])+c_coef*wfc[0]      -psi_old[0]
    psi_old[dim_x-1] = (c1*H.disorder[dim_x-1]-c2)*psi[dim_x-1]-c3*(psi[0]+psi[dim_x-2])+c_coef*wfc[dim_x-1]-psi_old[dim_x-1]
  else:
    psi_old[0]       = (c1*H.disorder[0]-c2)      *psi[0]      -c3*(psi[1])      +c_coef*wfc[0]      -psi_old[0]
    psi_old[dim_x-1] = (c1*H.disorder[dim_x-1]-c2)*psi[dim_x-1]-c3*(psi[dim_x-2])+c_coef*wfc[dim_x-1]-psi_old[dim_x-1]
  psi_old[1:dim_x-1] = (c1*H.disorder[1:dim_x-1]-c2)*psi[1:dim_x-1]-c3*(psi[2:dim_x]+psi[0:dim_x-2])+c_coef*wfc[1:dim_x-1]-psi_old[1:dim_x-1]
  return
"""

def chebyshev_step_1d_complex(wfc, H, psi, psi_old, c_coef, add_real, c1, c2, tab_c3):
#  print('wfc',wfc.shape,wfc.dtype)
#  print('psi',psi.shape,psi.dtype)
#  print('psi_old',psi_old.shape,psi_old.dtype)
#  print('disorder',H.disorder.shape)
#  print('in',wfc[0],psi[0],psi_old[0],c_coef,one_or_two,add_real)
  chebyshev_step_1d_complex_numba(H.tab_dim[0], H.tab_boundary_condition[0], H.disorder, wfc, psi, psi_old, c_coef, add_real, c1, c2, tab_c3)
  return

#@numba.jit(nopython=True,fastmath=True,cache=True)
@numba_decorator
def chebyshev_step_1d_complex_numba(dim_x, boundary, disorder, wfc, psi, psi_old, c_coef, add_real, c1, c2, tab_c3):
#  print('wfc',wfc.shape,wfc.dtype)
#  print('psi',psi.shape,psi.dtype)
#  print('psi_old',psi_old.shape,psi_old.dtype)
#  print('disorder',H.disorder.shape)
#  print('in',wfc[0],psi[0],psi_old[0],c_coef,one_or_two,add_real)
  if not(add_real):
    c_coef*=1j
  c3=tab_c3[0]
  if boundary=='periodic':
    psi_old[0]       = (c1*disorder[0]-c2)      *psi[0]      -c3*(psi[1]+psi[dim_x-1])+c_coef*wfc[0]      -psi_old[0]
    psi_old[dim_x-1] = (c1*disorder[dim_x-1]-c2)*psi[dim_x-1]-c3*(psi[0]+psi[dim_x-2])+c_coef*wfc[dim_x-1]-psi_old[dim_x-1]
  else:
    psi_old[0]       = (c1*disorder[0]-c2)      *psi[0]      -c3*(psi[1])      +c_coef*wfc[0]      -psi_old[0]
    psi_old[dim_x-1] = (c1*disorder[dim_x-1]-c2)*psi[dim_x-1]-c3*(psi[dim_x-2])+c_coef*wfc[dim_x-1]-psi_old[dim_x-1]
  psi_old[1:dim_x-1] = (c1*disorder[1:dim_x-1]-c2)*psi[1:dim_x-1]-c3*(psi[2:dim_x]+psi[0:dim_x-2])+c_coef*wfc[1:dim_x-1]-psi_old[1:dim_x-1]
  return

def chebyshev_step_1d_real(wfc, H, psi, psi_old, c_coef, add_real, c1, c2, tab_c3):
  chebyshev_step_1d_real_numba(H.tab_dim[0], H.tab_boundary_condition[0], H.disorder, wfc, psi, psi_old, c_coef, add_real, c1, c2, tab_c3)
  return

#@numba.jit(nopython=True,fastmath=True,cache=True)
@numba_decorator
def chebyshev_step_1d_real_numba(dim_x, boundary, disorder, wfc, psi, psi_old, c_coef, add_real, c1, c2, tab_c3):
  c3=tab_c3[0]
  if add_real:
    if boundary=='periodic':
      psi_old[0] = (c1*disorder[0]-c2)*psi[0]-c3*(psi[1]+psi[dim_x-1])+c_coef*wfc[0]-psi_old[0]
      psi_old[dim_x] = (c1*disorder[0]-c2)*psi[dim_x]-c3*(psi[dim_x+1]+psi[2*dim_x-1])+c_coef*wfc[dim_x]-psi_old[dim_x]
      psi_old[dim_x-1] = (c1*disorder[dim_x-1]-c2)*psi[dim_x-1]-c3*(psi[0]+psi[dim_x-2])+c_coef*wfc[dim_x-1]-psi_old[dim_x-1]
      psi_old[2*dim_x-1] = (c1*disorder[dim_x-1]-c2)*psi[2*dim_x-1]-c3*(psi[dim_x]+psi[2*dim_x-2])+c_coef*wfc[2*dim_x-1]-psi_old[2*dim_x-1]
    else:
      psi_old[0] = (c1*disorder[0]-c2)*psi[0]-c3*(psi[1])+c_coef*wfc[0]-psi_old[0]
      psi_old[dim_x] = (c1*disorder[0]-c2)*psi[dim_x]-c3*(psi[dim_x+1])+c_coef*wfc[dim_x]-psi_old[dim_x]
      psi_old[dim_x-1] = (c1*disorder[dim_x-1]-c2)*psi[dim_x-1]-c3*(psi[dim_x-2])+c_coef*wfc[dim_x-1]-psi_old[dim_x-1]
      psi_old[2*dim_x-1] = (c1*disorder[dim_x-1]-c2)*psi[2*dim_x-1]-c3*(psi[2*dim_x-2])+c_coef*wfc[2*dim_x-1]-psi_old[2*dim_x-1]
    psi_old[1:dim_x-1] = (c1*disorder[1:dim_x-1]-c2)*psi[1:dim_x-1]-c3*(psi[2:dim_x]+psi[0:dim_x-2])+c_coef*wfc[1:dim_x-1]-psi_old[1:dim_x-1]
    psi_old[dim_x+1:2*dim_x-1] = (c1*disorder[1:dim_x-1]-c2)*psi[dim_x+1:2*dim_x-1]-c3*(psi[dim_x+2:2*dim_x]+psi[dim_x:2*dim_x-2])+c_coef*wfc[dim_x+1:2*dim_x-1]-psi_old[dim_x+1:2*dim_x-1]
  else:
    if boundary=='periodic':
      psi_old[0] = (c1*disorder[0]-c2)*psi[0]-c3*(psi[1]+psi[dim_x-1])-c_coef*wfc[dim_x]-psi_old[0]
      psi_old[dim_x] = (c1*disorder[0]-c2)*psi[dim_x]-c3*(psi[dim_x+1]+psi[2*dim_x-1])+c_coef*wfc[0]-psi_old[dim_x]
      psi_old[dim_x-1] = (c1*disorder[dim_x-1]-c2)*psi[dim_x-1]-c3*(psi[0]+psi[dim_x-2])-c_coef*wfc[2*dim_x-1]-psi_old[dim_x-1]
      psi_old[2*dim_x-1] = (c1*disorder[dim_x-1]-c2)*psi[2*dim_x-1]-c3*(psi[dim_x]+psi[2*dim_x-2])+c_coef*wfc[dim_x-1]-psi_old[2*dim_x-1]
    else:
      psi_old[0] = (c1*disorder[0]-c2)*psi[0]-c3*(psi[1])-c_coef*wfc[dim_x]-psi_old[0]
      psi_old[dim_x] = (c1*disorder[0]-c2)*psi[dim_x]-c3*(psi[dim_x+1])+c_coef*wfc[0]-psi_old[dim_x]
      psi_old[dim_x-1] = (c1*disorder[dim_x-1]-c2)*psi[dim_x-1]-c3*(psi[dim_x-2])-c_coef*wfc[2*dim_x-1]-psi_old[dim_x-1]
      psi_old[2*dim_x-1] = (c1*disorder[dim_x-1]-c2)*psi[2*dim_x-1]-c3*(psi[2*dim_x-2])+c_coef*wfc[dim_x-1]-psi_old[2*dim_x-1]
    psi_old[1:dim_x-1] = (c1*disorder[1:dim_x-1]-c2)*psi[1:dim_x-1]-c3*(psi[2:dim_x]+psi[0:dim_x-2])-c_coef*wfc[dim_x+1:2*dim_x-1]-psi_old[1:dim_x-1]
    psi_old[dim_x+1:2*dim_x-1] = (c1*disorder[1:dim_x-1]-c2)*psi[dim_x+1:2*dim_x-1]-c3*(psi[dim_x+2:2*dim_x]+psi[dim_x:2*dim_x-2])+c_coef*wfc[1:dim_x-1]-psi_old[dim_x+1:2*dim_x-1]
  return

"""
def chebyshev_step_2d_complex(wfc, H, psi, psi_old, c_coef, add_real, c1, c2, tab_c3):
#  print('using chebyshev_step_2d_complex')
# Specific code for dimension 2
  if not(add_real):
    c_coef*=1j
  c3_x=tab_c3[0]
  c3_y=tab_c3[1]
  dim_x = H.tab_dim[0]
  dim_y = H.tab_dim[1]
  b_x = H.tab_boundary_condition[0]
  b_y = H.tab_boundary_condition[1]
# The code propagates along the x axis, computing one vector (along y) at each iteration
# To decrase the number of memory accesses, 3 temporary vectors are used, containing the current x row, the previous and the next rows
# To simplify the code, the temporary vectors have 2 additional components, set to zero for fixed boundary conditions and to the wrapped values for periodic boundary conditions
# Create the 3 temporary vectors
  p_old=np.zeros(dim_y+2,dtype=np.complex128)
  p_current=np.zeros(dim_y+2,dtype=np.complex128)
  p_new=np.zeros(dim_y+2,dtype=np.complex128)
# If periodic boundary conditions along x, initialize p_current to the last row, otherwise 0
  if b_x=='periodic':
    p_current[1:dim_y+1]=psi[(dim_x-1)*dim_y:dim_x*dim_y]
# Initialize the next row, which will become the current row in the first iteration of the loop
  p_new[1:dim_y+1]=psi[0:dim_y]
# If periodic boundary condition along y, copy the first and last components
  if b_y=='periodic':
    p_new[0]=p_new[dim_y]
    p_new[dim_y+1]=p_new[1]
  for i in range(dim_x):
    p_temp=p_old
    p_old=p_current
    p_current=p_new
    p_new=p_temp
    if i<dim_x-1:
# The generic row
      p_new[1:dim_y+1]=psi[(i+1)*dim_y:(i+2)*dim_y]
    else:
# If in last row, put in p_new the first row if periodic along x, 0 otherwise )
      if b_x=='periodic':
        p_new[1:dim_y+1]=psi[0:dim_y]
      else:
        p_new[1:dim_y+1]=0.0
# If periodic boundary condition along y, copy the first and last components
    if b_y=='periodic':
      p_new[0]=p_new[dim_y]
      p_new[dim_y+1]=p_new[1]
    i_low=i*dim_y
    i_high=i_low+dim_y
# Ready to treat the current row
#        psi_old[i*dim_y:(i+1)*dim_y] = (c1*H.disorder[i,0:dim_y]-c2)*p_current[1:dim_y+1] - c3_y*(p_current[2:dim_y+2]+ p_current[0:dim_y]) - c3_x*(p_old[1:dim_y+1]+p_new[1:dim_y+1]) + c_coef*wfc[i*dim_y:(i+1)*dim_y] - psi_old[i*dim_y:(i+1)*dim_y]
    psi_old[i_low:i_high] = (c1*H.disorder[i,0:dim_y]-c2)*p_current[1:dim_y+1] - c3_y*(p_current[2:dim_y+2]+ p_current[0:dim_y]) - c3_x*(p_old[1:dim_y+1]+p_new[1:dim_y+1]) + c_coef*wfc[i_low:i_high] - psi_old[i_low:i_high]
  return
"""
def chebyshev_step_2d_complex(wfc, H, psi, psi_old, c_coef, add_real, c1, c2, tab_c3):
  chebyshev_step_2d_complex_numba(H.tab_dim[0], H.tab_dim[1], H.tab_boundary_condition[0], H.tab_boundary_condition[1], H.disorder, wfc, psi, psi_old, c_coef, add_real, c1, c2, tab_c3)
  return

@numba_decorator
def chebyshev_step_2d_complex_numba(dim_x, dim_y, b_x, b_y, disorder, wfc, psi, psi_old, c_coef, add_real, c1, c2, tab_c3):
#  print('using chebyshev_step_2d_complex')
# Specific code for dimension 2
  if not(add_real):
    c_coef*=1j
  c3_x=tab_c3[0]
  c3_y=tab_c3[1]
# The code propagates along the x axis, computing one vector (along y) at each iteration
# To decrase the number of memory accesses, 3 temporary vectors are used, containing the current x row, the previous and the next rows
# To simplify the code, the temporary vectors have 2 additional components, set to zero for fixed boundary conditions and to the wrapped values for periodic boundary conditions
# Create the 3 temporary vectors
  p_old=np.zeros(dim_y+2,dtype=np.complex128)
  p_current=np.zeros(dim_y+2,dtype=np.complex128)
  p_new=np.zeros(dim_y+2,dtype=np.complex128)
# If periodic boundary conditions along x, initialize p_current to the last row, otherwise 0
  if b_x=='periodic':
    p_current[1:dim_y+1]=psi[(dim_x-1)*dim_y:dim_x*dim_y]
# Initialize the next row, which will become the current row in the first iteration of the loop
  p_new[1:dim_y+1]=psi[0:dim_y]
# If periodic boundary condition along y, copy the first and last components
  if b_y=='periodic':
    p_new[0]=p_new[dim_y]
    p_new[dim_y+1]=p_new[1]
  for i in range(dim_x):
    p_temp=p_old
    p_old=p_current
    p_current=p_new
    p_new=p_temp
    if i<dim_x-1:
# The generic row
      p_new[1:dim_y+1]=psi[(i+1)*dim_y:(i+2)*dim_y]
    else:
# If in last row, put in p_new the first row if periodic along x, 0 otherwise )
      if b_x=='periodic':
        p_new[1:dim_y+1]=psi[0:dim_y]
      else:
        p_new[1:dim_y+1]=0.0
# If periodic boundary condition along y, copy the first and last components
    if b_y=='periodic':
      p_new[0]=p_new[dim_y]
      p_new[dim_y+1]=p_new[1]
    i_low=i*dim_y
    i_high=i_low+dim_y
# Ready to treat the current row
#        psi_old[i*dim_y:(i+1)*dim_y] = (c1*H.disorder[i,0:dim_y]-c2)*p_current[1:dim_y+1] - c3_y*(p_current[2:dim_y+2]+ p_current[0:dim_y]) - c3_x*(p_old[1:dim_y+1]+p_new[1:dim_y+1]) + c_coef*wfc[i*dim_y:(i+1)*dim_y] - psi_old[i*dim_y:(i+1)*dim_y]
    psi_old[i_low:i_high] = (c1*disorder[i,0:dim_y]-c2)*p_current[1:dim_y+1] - c3_y*(p_current[2:dim_y+2]+ p_current[0:dim_y]) - c3_x*(p_old[1:dim_y+1]+p_new[1:dim_y+1]) + c_coef*wfc[i_low:i_high] - psi_old[i_low:i_high]
#  p_old=None
#  p_current=None
#  p_new=None
  return

def chebyshev_step_2d_real(wfc, H, psi, psi_old, c_coef, add_real, c1, c2, tab_c3):
  chebyshev_step_2d_real_numba(H.tab_dim[0], H.tab_dim[1], H.tab_boundary_condition[0], H.tab_boundary_condition[1], H.disorder, wfc, psi, psi_old, c_coef, add_real, c1, c2, tab_c3)
  return

@numba_decorator
#@numba.jit(nopython=True,fastmath=True,cache=True)
def chebyshev_step_2d_real_numba(dim_x, dim_y, b_x, b_y, disorder, wfc, psi, psi_old, c_coef, add_real, c1, c2, tab_c3):
#  print('toto')
# Specific code for dimension 2
  c3_x=tab_c3[0]
  c3_y=tab_c3[1]
  ntot = dim_x*dim_y
# The code propagates along the x axis, computing one vector (along y) at each iteration
# To decrase the number of memory accesses, 3 temporary vectors are used, containing the current x row, the previous and the next rows
# To simplify the code, the temporary vectors have 2 additional components, set to zero for fixed boundary conditions and to the wrapped values for periodic boundary conditions
# Create the 3 temporary vectors
  p_old=np.zeros(2*dim_y+4)
  p_current=np.zeros(2*dim_y+4)
  p_new=np.zeros(2*dim_y+4)
# If periodic boundary conditions along x, initialize p_current to the last row, otherwise 0
  if b_x=='periodic':
    p_current[1:dim_y+1]=psi[(dim_x-1)*dim_y:dim_x*dim_y]
    p_current[dim_y+3:2*dim_y+3]=psi[ntot+(dim_x-1)*dim_y:ntot+dim_x*dim_y]
# Initialize the next row, which will become the current row in the first iteration of the loop
  p_new[1:dim_y+1]=psi[0:dim_y]
  p_new[dim_y+3:2*dim_y+3]=psi[ntot:ntot+dim_y]
# If periodic boundary condition along y, copy the first and last components
  if b_y=='periodic':
    p_new[0]=p_new[dim_y]
    p_new[dim_y+1]=p_new[1]
    p_new[dim_y+2]=p_new[2*dim_y+2]
    p_new[2*dim_y+3]=p_new[dim_y+3]
  for i in range(dim_x):
    p_temp=p_old
    p_old=p_current
    p_current=p_new
    p_new=p_temp
    if i<dim_x-1:
# The generic row
      p_new[1:dim_y+1]=psi[(i+1)*dim_y:(i+2)*dim_y]
      p_new[dim_y+3:2*dim_y+3]=psi[ntot+(i+1)*dim_y:ntot+(i+2)*dim_y]
    else:
# If in last row, put in p_new the first row if periodic along x, 0 otherwise )
      if b_x=='periodic':
        p_new[1:dim_y+1]=psi[0:dim_y]
        p_new[dim_y+3:2*dim_y+3]=psi[ntot:ntot+dim_y]
      else:
        p_new[1:2*dim_y+3]=0.0
# If periodic boundary condition along y, copy the first and last components
    if b_y=='periodic':
      p_new[0]=p_new[dim_y]
      p_new[dim_y+1]=p_new[1]
      p_new[dim_y+2]=p_new[2*dim_y+2]
      p_new[2*dim_y+3]=p_new[dim_y+3]
    i_low=i*dim_y
    i_high=i_low+dim_y
# Ready to treat the current row
#        psi_old[i*dim_y:(i+1)*dim_y] = (c1*H.disorder[i,0:dim_y]-c2)*p_current[1:dim_y+1] - c3_y*(p_current[2:dim_y+2]+ p_current[0:dim_y]) - c3_x*(p_old[1:dim_y+1]+p_new[1:dim_y+1]) + c_coef*wfc[i*dim_y:(i+1)*dim_y] - psi_old[i*dim_y:(i+1)*dim_y]
    if add_real:
      psi_old[i_low:i_high] = (c1*disorder[i,0:dim_y]-c2)*p_current[1:dim_y+1] - c3_y*(p_current[2:dim_y+2]+ p_current[0:dim_y]) - c3_x*(p_old[1:dim_y+1]+p_new[1:dim_y+1]) + c_coef*wfc[i_low:i_high] - psi_old[i_low:i_high]
      psi_old[ntot+i_low:ntot+i_high] = (c1*disorder[i,0:dim_y]-c2)*p_current[dim_y+3:2*dim_y+3] - c3_y*(p_current[dim_y+4:2*dim_y+4]+ p_current[dim_y+2:2*dim_y+2]) - c3_x*(p_old[dim_y+3:2*dim_y+3]+p_new[dim_y+3:2*dim_y+3]) + c_coef*wfc[ntot+i_low:ntot+i_high] - psi_old[ntot+i_low:ntot+i_high]
    else:
      psi_old[i_low:i_high] = (c1*disorder[i,0:dim_y]-c2)*p_current[1:dim_y+1] - c3_y*(p_current[2:dim_y+2]+ p_current[0:dim_y]) - c3_x*(p_old[1:dim_y+1]+p_new[1:dim_y+1]) - c_coef*wfc[ntot+i_low:ntot+i_high] - psi_old[i_low:i_high]
      psi_old[ntot+i_low:ntot+i_high] = (c1*disorder[i,0:dim_y]-c2)*p_current[dim_y+3:2*dim_y+3] - c3_y*(p_current[dim_y+4:2*dim_y+4]+ p_current[dim_y+2:2*dim_y+2]) - c3_x*(p_old[dim_y+3:2*dim_y+3]+p_new[dim_y+3:2*dim_y+3]) + c_coef*wfc[i_low:i_high] - psi_old[ntot+i_low:ntot+i_high]
#  print('no_cffi psi_old',psi_old[dim_x],psi_old[dim_x+1],psi_old[2*dim_x-2],psi_old[2*dim_x-1])
#  print('no_cffi psi    ',psi[dim_x],psi[dim_x+1],psi[2*dim_x-2],psi[2*dim_x-1])
#  print('no_cffi wfc    ',wfc[dim_x],wfc[dim_x+1],wfc[2*dim_x-2],wfc[2*dim_x-1])
#  print('no_cffi wfc_dec',wfc[0],wfc[1],wfc[dim_x-2],wfc[dim_x-1])
# ,H.two_over_delta_e,H.two_e0_over_delta_e,H.tab_tunneling[0],c_coef,one_or_two,add_real)
  return

def chebyshev_step_3d_complex(wfc, H, psi, psi_old, c_coef, add_real, c1, c2, tab_c3):
  chebyshev_step_3d_complex_numba(H.tab_dim[0], H.tab_dim[1], H.tab_dim[2], H.tab_boundary_condition[0], H.tab_boundary_condition[1],  H.tab_boundary_condition[2], H.disorder, wfc, psi, psi_old, c_coef, add_real, c1, c2, tab_c3)
  return

@numba_decorator
#@numba.jit(nopython=True,fastmath=True,cache=True)
def chebyshev_step_3d_complex_numba(dim_x, dim_y, dim_z, b_x, b_y, b_z, disorder, wfc, psi, psi_old, c_coef, add_real, c1, c2, tab_c3):
#  print('using chebyshev_step_3d_complex')
  if not(add_real):
    c_coef*=1j
  c3_x=tab_c3[0]
  c3_y=tab_c3[1]
  c3_z=tab_c3[2]
  dim_transverse = dim_y*dim_z
# The code propagates along the x axis, computing one vector (along y and z) at each iteration
# To decrase the number of memory accesses, 3 temporary vectors are used, containing the current x plane, the previous and the next planes
# To simplify the code, the temporary vectors have 2 additional components in each direction, set to zero for fixed boundary conditions and to the wrapped values for periodic boundary conditions
# Create the 3 temporary vectors
  p_old=np.zeros((dim_y+2)*(dim_z+2),dtype=np.complex128)
  p_current=np.zeros((dim_y+2)*(dim_z+2),dtype=np.complex128)
  p_new=np.zeros((dim_y+2)*(dim_z+2),dtype=np.complex128)
# If periodic boundary conditions along x, initialize p_current to the last plane, otherwise 0
  if b_x=='periodic':
    for j in range(dim_y):
      p_current[(j+1)*(dim_z+2)+1:(j+2)*(dim_z+2)-1]=psi[(dim_x-1)*dim_transverse+j*dim_z:(dim_x-1)*dim_transverse+(j+1)*dim_z]
# Initialize the next plane, which will become the current plane in the first iteration of the loop
  for j in range(dim_y):
      p_new[(j+1)*(dim_z+2)+1:(j+2)*(dim_z+2)-1]=psi[j*dim_z:(j+1)*dim_z]
# If periodic boundary condition along y, copy the first and last row along z
  if b_y=='periodic':
    p_new[1:dim_z+1]=p_new[(dim_y)*(dim_z+2)+1:(dim_y+1)*(dim_z+2)-1]
    p_new[(dim_y+1)*(dim_z+2)+1:(dim_y+2)*(dim_z+2)-1]=p_new[dim_z+3:2*dim_z+3]
# If periodic boundary condition along z, copy the first and last row along y
  if b_z=='periodic':
    p_new[dim_z+2:(dim_y+1)*(dim_z+2):dim_z+2]=p_new[2*dim_z+2:(dim_y+1)*(dim_z+2)+dim_z:dim_z+2]
    p_new[2*dim_z+3:(dim_y+1)*(dim_z+2)+dim_z+1:dim_z+2]=p_new[dim_z+3:(dim_y+1)*(dim_z+2)+1:dim_z+2]
# this is the main loop for propagation along the x direction
  for i in range(dim_x):
    p_temp=p_old
    p_old=p_current
    p_current=p_new
    p_new=p_temp
    if i<dim_x-1:
# The generic plane
      for j in range(dim_y):
        p_new[(j+1)*(dim_z+2)+1:(j+2)*(dim_z+2)-1]=psi[(i+1)*dim_transverse+j*dim_z:(i+1)*dim_transverse+(j+1)*dim_z]
    else:
# If in last plane, put in p_new the first plane if periodic along x, 0 otherwise )
      if b_x=='periodic':
        for j in range(dim_y):
          p_new[(j+1)*(dim_z+2)+1:(j+2)*(dim_z+2)-1]=psi[j*dim_z:(j+1)*dim_z]
      else:
        for j in range(dim_y):
          p_new[(j+1)*(dim_z+2)+1:(j+2)*(dim_z+2)-1]=0.0
# If periodic boundary condition along y, copy the first and last row along z
    if b_y=='periodic':
      p_new[1:dim_z+1]=p_new[(dim_y)*(dim_z+2)+1:(dim_y+1)*(dim_z+2)-1]
      p_new[(dim_y+1)*(dim_z+2)+1:(dim_y+2)*(dim_z+2)-1]=p_new[dim_z+3:2*dim_z+3]
# If periodic boundary condition along z, copy the first and last row along y
    if b_z=='periodic':
      p_new[dim_z+2:(dim_y+1)*(dim_z+2):dim_z+2]=p_new[2*dim_z+2:(dim_y+1)*(dim_z+2)+dim_z:dim_z+2]
      p_new[2*dim_z+3:(dim_y+1)*(dim_z+2)+dim_z+1:dim_z+2]=p_new[dim_z+3:(dim_y+1)*(dim_z+2)+1:dim_z+2]
    for j in range(dim_y):
      i_low=i*dim_transverse+j*dim_z
      i_high=i_low+dim_z
# Ready to treat the current row
#        psi_old[i*dim_y:(i+1)*dim_y] = (c1*H.disorder[i,0:dim_y]-c2)*p_current[1:dim_y+1] - c3_y*(p_current[2:dim_y+2]+ p_current[0:dim_y]) - c3_x*(p_old[1:dim_y+1]+p_new[1:dim_y+1]) + c_coef*wfc[i*dim_y:(i+1)*dim_y] - psi_old[i*dim_y:(i+1)*dim_y]
      psi_old[i_low:i_high] = (c1*disorder[i,j,0:dim_z]-c2)*p_current[(j+1)*(dim_z+2)+1:(j+1)*(dim_z+2)+dim_z+1]\
        - c3_y*(p_current[(j+2)*(dim_z+2)+1:(j+2)*(dim_z+2)+dim_z+1]+ p_current[j*(dim_z+2)+1:j*(dim_z+2)+dim_z+1])\
        - c3_z*(p_current[(j+1)*(dim_z+2)+2:(j+1)*(dim_z+2)+dim_z+2]+ p_current[(j+1)*(dim_z+2):(j+1)*(dim_z+2)+dim_z])\
        - c3_x*(p_old[(j+1)*(dim_z+2)+1:(j+1)*(dim_z+2)+dim_z+1]+p_new[(j+1)*(dim_z+2)+1:(j+1)*(dim_z+2)+dim_z+1])\
        + c_coef*wfc[i_low:i_high] - psi_old[i_low:i_high]
#  p_old=None
#  p_current=None
#  p_new=None
#  print('psi',psi)
#  print('psi_old',psi_old)
  return

def chebyshev_propagation_ctypes(wfc, H, propagation, timing):
  local_wfc = wfc.ravel()
  ntot = H.hs_dim
  max_order = propagation.tab_coef.size-1
  assert max_order%2==0,"Max order {} must be an even number".format(max_order)
  if propagation.data_layout=='real':
    psi_old = np.zeros(2*ntot)
    psi     = np.zeros(2*ntot)
#      print('local_wfc',local_wfc.shape,local_wfc.dtype)
#      print('psi',psi.shape,psi.dtype)
#      print('psi_old',psi_old.shape,psi_old.dtype)
#      print('disorder',H.disorder.shape,H.disorder.dtype)
#      print('tab_coef',propagation.tab_coef.shape,propagation.tab_coef.dtype)
    nonlinear_phase = propagation.chebyshev_ctypes_lib.chebyshev_real(H.dimension, np.asarray(H.tab_dim,dtype=np.intc), max_order, H.array_boundary_condition,\
        local_wfc, psi, psi_old, H.disorder.ravel(), propagation.tab_coef, np.asarray(H.tab_tunneling),\
        H.two_over_delta_e, H.two_e0_over_delta_e, H.interaction*propagation.delta_t, H.medium_energy*propagation.delta_t)
  else:
    psi_old = np.zeros(ntot,dtype=np.complex128)
    psi     = np.zeros(ntot,dtype=np.complex128)
    nonlinear_phase = propagation.chebyshev_ctypes_lib.chebyshev_complex(H.dimension, np.asarray(H.tab_dim,dtype=np.intc), max_order, H.array_boundary_condition,\
        local_wfc, psi, psi_old, H.disorder.ravel(), propagation.tab_coef, np.asarray(H.tab_tunneling),\
        H.two_over_delta_e, H.two_e0_over_delta_e, H.interaction*propagation.delta_t, H.medium_energy*propagation.delta_t)
#    print(nonlinear_phase[0])
  timing.MAX_NONLINEAR_PHASE = max(nonlinear_phase,timing.MAX_NONLINEAR_PHASE)
  return

def chebyshev_propagation_generic(wfc, H, propagation,timing):
#  print('using chebyshev_propagation_generic')
#  print(propagation.chebyshev_step,H.apply_h)
  ntot = H.hs_dim
  max_order = propagation.tab_coef.size-1
  local_wfc = wfc.ravel()
  assert max_order%2==0,"Max order {} must be an even number".format(max_order)
  if propagation.data_layout == 'real':
    psi_old = np.zeros(2*ntot)
  else:
    psi_old = np.zeros(ntot,dtype=np.complex128)
  psi = propagation.tab_coef[-1] * local_wfc
  c1 = 2.0*H.two_over_delta_e
  c2 = 2.0*H.two_e0_over_delta_e
  tab_c3 = 2.0*np.asarray(H.tab_tunneling)*H.two_over_delta_e
  propagation.chebyshev_step(local_wfc,H,psi,psi_old,propagation.tab_coef[-2],False,c1,c2,tab_c3)
  for order in range(propagation.tab_coef.size-3,0,-2):
#      print(order,psi[0])
    propagation.chebyshev_step(local_wfc,H,psi_old,psi,propagation.tab_coef[order],True,c1,c2,tab_c3)
    propagation.chebyshev_step(local_wfc,H,psi,psi_old,propagation.tab_coef[order-1],False,c1,c2,tab_c3)
  c1 = H.two_over_delta_e
  c2 = H.two_e0_over_delta_e
  tab_c3 = np.asarray(H.tab_tunneling)*H.two_over_delta_e
  propagation.chebyshev_step(local_wfc,H,psi_old,psi,propagation.tab_coef[0],True,c1,c2,tab_c3)

  if H.interaction==0.0:
    phase = propagation.delta_t*H.medium_energy
#      phase = 0.0
    cos_phase = math.cos(phase)
    sin_phase = math.sin(phase)
  else:
    if propagation.data_layout == 'real':
      nonlinear_phase = propagation.delta_t*H.interaction*(psi[0:ntot]**2+psi[ntot:2*ntot]**2)
    else:
      nonlinear_phase = propagation.delta_t*H.interaction*(np.real(psi)**2+np.imag(psi)**2)
    timing.MAX_NONLINEAR_PHASE = max(timing.MAX_NONLINEAR_PHASE,np.amax(nonlinear_phase))
    phase=propagation.delta_t*H.medium_energy+nonlinear_phase
    cos_phase = np.cos(phase)
    sin_phase = np.sin(phase)
  if propagation.data_layout == 'real':
      local_wfc[0:ntot] = psi[0:ntot]*cos_phase+psi[ntot:2*ntot]*sin_phase
      local_wfc[ntot:2*ntot] = psi[ntot:2*ntot]*cos_phase-psi[0:ntot]*sin_phase
  else:
      local_wfc[:] = psi[:] * (cos_phase-1j*sin_phase)
#  print(psi[2000],wfc[2000])
#    print('endend_no_cffi',local_wfc[0],local_wfc[1],local_wfc[ntot-1])
  return



def gross_pitaevskii(t, wfc, H, data_layout, rhs, timing):
    """Returns rhs of Gross-Pitaevskii equation with discretized space
    For data_layout == 'complex':
      wfc is assumed to be in format where
      wfc[0:2*ntot:2] contains the real part of the wavefunction and
      wfc[1:2*ntot:2] contains the imag part of the wavefunction.
    For data_layout == 'real':
      wfc is assumed to be in format where
      wfc[0:ntot] contains the real part of the wavefunction and
      wfc[ntot:2*ntot] contains the imag part of the wavefunction.
    """
    start_time = timeit.default_timer()
    if (data_layout=='real'):
      H.apply_minus_i_h_gpe_real(wfc, rhs)
#      print('inside gpe real',wfc[100],rhs[100])
    else:
#      print('inside gpe wfc',wfc.dtype,wfc.shape)spectral_function,
#      print('inside gpe rhs',rhs.dtype,rhs.shape)
      H.apply_minus_i_h_gpe_complex(wfc, rhs)
#      print('inside gpe complex',wfc[200],wfc[201],rhs[200],rhs[201])
    timing.GPE_TIME+=(timeit.default_timer() - start_time)
    timing.GPE_NOPS+=16.0*H.hs_dim
    timing.N_SOLOUT += 1
#    print('Inside gross_pitaevskii t = ',t)
    return rhs



class Spectral_function:
  def __init__(self,e_min,e_max,e_resolution,multiplicative_factor_for_interaction_in_spectral_function, n_kpm, want_ctypes_for_spectral_function, allow_unsafe_energy_bounds, H):
    e_range = e_max - e_min
    e_middle = 0.5*(e_max+e_min)
    self.n_pts = int(e_range/e_resolution+1.5)
# In case e_range/e_resolution is not an integer, I keep e_resolution and rescale e_range
    self.e_min = e_middle - 0.5*e_resolution*(self.n_pts-1)
    self.e_max = e_middle + 0.5*e_resolution*(self.n_pts-1)
# The KPM calculation is performed in the interval [e_min-e_resolution, e_max+e_resolution]
# This avoids the divergence of the denominator at edges
# Create the array of x values for which the spectral function is computed
    self.tab_x = np.linspace(-1.0+2.0/(self.n_pts+1),1.0-2.0/(self.n_pts+1),num=self.n_pts)
#    print(self.tab_x)
    self.tab_energies = np.linspace(self.e_min,self.e_max,num=self.n_pts)
    self.tab_spectrum = np.zeros(self.n_pts)
    self.e_resolution = e_resolution
    self.multiplicative_factor_for_interaction = multiplicative_factor_for_interaction_in_spectral_function
    self.n_kpm = n_kpm
    self.want_ctypes_for_spectral_function = want_ctypes_for_spectral_function
# Check whether the energy bounds are sufficient to enclose all the energy spectrum
# This is a simple, not sufficient test, which only wants to avoid simple mistakes
# A more accurate test would require to call H.energy_range for each disorder realization
    if self.e_min>0.0 or self.e_max<2.0*H.diagonal:
      if allow_unsafe_energy_bounds:
        print('WARNING, the energy range for the spectral function is probably too small\n'\
              'the minimum energy is ',self.e_min,' and should be smaller than 0.0\n'\
              'the maximum energy is ',self.e_max,' and should be larger  than ',2.0*H.diagonal)
      else:
        print('The energy range for the spectral function is too small, I stop!\n'\
              'the minimum energy is ',self.e_min,' and should be smaller than 0.0\n'\
              'the maximum energy is ',self.e_max,' and should be larger  than ',2.0*H.diagonal)
        sys.exit()
# Is there a ctypes implementation?
    self.has_chebyshev_kpm_routine = False
    if not H.spin_one_half and self.want_ctypes_for_spectral_function:
      try:
        import ctypes
        import numpy.ctypeslib as ctl
        self.has_chebyshev_kpm_routine = True
        self.chebyshev_ctypes_lib=ctypes.CDLL(anderson.__path__[0]+"/ctypes/chebyshev.so")
        self.chebyshev_ctypes_lib.chebyshev_kpm_step.argtypes = [ctypes.c_int, ctl.ndpointer(np.intc), ctl.ndpointer(np.intc),\
          ctl.ndpointer(np.complex128), ctl.ndpointer(np.complex128), ctl.ndpointer(np.float64), ctl.ndpointer(np.float64), ctypes.c_double, ctypes.c_double]
        self.chebyshev_ctypes_lib.chebyshev_kpm_step.restype = None
        if not hasattr(self.chebyshev_ctypes_lib,'chebyshev_kpm_step'):
          self.has_chebyshev_kpm_routine = False
          self.chebyshev_ctypes_lib = None
          if H.seed == 0 :
            print("\nWarning, chebyshev C library found, but without routine for KPM computation of the spectral function, this uses the slow Python version\n")
      except:
        self.has_chebyshev_kpm_routine = False
        self.chebyshev_ctypes_lib = None
        if H.seed == 0 :
          print("\nWarning, no ctypes module, no numpy.ctypeslib module or no chebyshev C library found, this uses the slow Python version!\n")
    self.use_ctypes = self.has_chebyshev_kpm_routine and self.want_ctypes_for_spectral_function
    if self.use_ctypes:
      self.chebyshev_kpm_routine = self.chebyshev_kpm_step_ctypes
    else:
      self.chebyshev_kpm_routine = self.chebyshev_kpm_step
    return


  def chebyshev_kpm_step(self, H, psi, psi_old, c1, c2):
# Generic code uses the sparse multiplication
    psi_old[:] = c1*H.apply_h(psi)-c2*psi[:]-psi_old[:]
#  print('psi',psi)
#  print('psi_old',psi_old)
    return

  def chebyshev_kpm_step_ctypes(self, H, psi, psi_old, c1, c2):
    self.chebyshev_ctypes_lib.chebyshev_kpm_step(H.dimension, np.asarray(H.tab_dim,dtype=np.intc), H.array_boundary_condition,\
      psi.ravel(), psi_old.ravel(), H.disorder.ravel(), np.asarray(H.tab_tunneling), c1, c2)
    return

  def normalize(self, n):
    self.tab_spectrum /= n
    return

  def mpi_merge(self, comm, timing):
    start_mpi_time = timeit.default_timer()
    try:
      from mpi4py import MPI
    except ImportError:
      print("mpi4py is not found!")
      return
    toto = np.empty_like(self.tab_spectrum)
    comm.Reduce(self.tab_spectrum,toto)
    self.tab_spectrum = np.copy(toto)
    timing.MPI_TIME+=(timeit.default_timer() - start_mpi_time)
    return


  def compute_spectral_function(self, i_seed, geometry, initial_state, H, timing, debug=False, build_disorder=True, build_initial_state=True):
    start_dummy_time=timeit.default_timer()
    if build_disorder and (H.randomize_hamiltonian or H.seed==0):
      if geometry.reproducible_randomness:
        seed = i_seed+1234+H.custom_seed
      else:
        seed = None
#      print(i_seed,seed)
      H.generate_disorder(seed)
#      H.energy_range(accurate=propagation.accurate_bounds)
#    print(H.disorder)
    if build_initial_state and (initial_state.randomize_initial_state or initial_state.seed==0):
      if geometry.reproducible_randomness:
        seed = i_seed+2345+H.custom_seed
      else:
        seed = None
      initial_state.prepare_initial_state(seed)
    timing.DUMMY_TIME+=(timeit.default_timer() - start_dummy_time)
    start_kpm_time = timeit.default_timer()
    if H.interaction*self.multiplicative_factor_for_interaction != 0.0:
# Modify the disorder to take into account part of the interaction term
      H.disorder = H.disorder + H.interaction*self.multiplicative_factor_for_interaction*(np.abs(initial_state.wfc)**2)
# If there is no specific apply_h routine, a sparse version of the Hamiltonian is used
# This sparse matrix must be generated
#    if not H.has_specific_apply_h_routine:
#      H.generate_sparse_matrix()
#  psi_0 = initial_state.wfc.ravel()
    psi = copy.deepcopy(initial_state.wfc.ravel())
    psi_old = np.zeros_like(psi)
    n_kpm = self.n_kpm
# The calculation is performed in the interval [e_min-e_resolution, e_max+e_resolution]
# This avoids the divergence of the denominator at edges
    c1 = 2.0/(self.e_max-self.e_min+2.0*self.e_resolution)
    c2 = 0.5*c1*(self.e_max+self.e_min)
    tab_mu = np.zeros(n_kpm+1)
# Jackson damping
# tab_g = np.ones(n_kpm+1)
    tab_g = (np.linspace(n_kpm+2,1,num=n_kpm+1)*np.cos(np.pi*np.linspace(0,n_kpm+1,num=n_kpm+1)/(n_kpm+2))\
           +np.sin(np.pi*np.linspace(0,n_kpm+1,num=n_kpm+1)/(n_kpm+2))/np.tan(np.pi/(n_kpm+2)))/(n_kpm+2)
#  print(tab_g)
    tab_mu[0] = np.vdot(psi,psi).real*H.delta_vol
    self.chebyshev_kpm_routine(H, psi, psi_old, c1, c2)
    c1 *= 2.0
    c2 *= 2.0
    tab_mu[1] = np.vdot(psi,psi_old).real*H.delta_vol
# The various Chebyshev polynomials are computed by recursion
# Initialize T_0 and T_1
    tab_T_old = np.ones(self.n_pts)
    tab_T = self.tab_x*tab_T_old
    tab_spectrum = tab_mu[0]*tab_T_old+2.0*tab_mu[1]*tab_T*tab_g[1]
    """
# Range for the old method
    for i in range(2,n_kpm+1):
      psi_old, psi = psi, psi_old
      self.chebyshev_kpm_routine(H, psi, psi_old, c1, c2)
# The old method
      tab_mu[i] = np.vdot(initial_state.wfc.ravel(),psi_old).real*H.delta_vol
#      print(i,tab_mu[i])

    """
# The improved method which saves a factor 2
    tab_mu[2] = 2.0*np.vdot(psi_old,psi_old).real*H.delta_vol-tab_mu[0]
# Range for the improved method
    for i in range(2,(n_kpm+1)//2+1):
      psi_old, psi = psi, psi_old
      self.chebyshev_kpm_routine(H, psi, psi_old, c1, c2)
      tab_mu[2*i-1] = 2.0*np.vdot(psi,psi_old).real*H.delta_vol-tab_mu[1]
#      print(2*i-1,tab_mu[2*i-1])
      if 2*i<n_kpm+1:
        tab_mu[2*i] = 2.0*np.vdot(psi_old,psi_old).real*H.delta_vol-tab_mu[0]
#        print(2*i,tab_mu[2*i])
# print(tab_mu)
    timing.KPM_TIME += (timeit.default_timer() - start_kpm_time)
# Count of operations: (8+7*H.dimension)*H.hs_dim comes from each kpm routine (assuming it is the ctypes version)
# 8*H.hs_dim comes from each scalar product (vdot operation)
    timing.KPM_NOPS += n_kpm*(12.0+3.5*H.dimension)*H.hs_dim
    start_dummy_time = timeit.default_timer()
# Restore the initial disorder
    if H.interaction*self.multiplicative_factor_for_interaction != 0.0:
      H.disorder = H.disorder - H.interaction*self.multiplicative_factor_for_interaction*(np.abs(initial_state.wfc)**2)
    timing.DUMMY_TIME+=(timeit.default_timer() - start_dummy_time)
    start_spectrum_time = timeit.default_timer()
# If the number of operations is large enough, use the numba version
# Otherwise, stick to the simple Python version
    if self.n_pts*n_kpm>1.e6:
      tab_spectrum = compute_spectral_function_from_mu(n_kpm,tab_T,tab_T_old,self.tab_x,tab_mu,tab_g,tab_spectrum)
    else:
      for i in range(2,n_kpm+1):
        tab_T_old = 2.0*self.tab_x*tab_T-tab_T_old
        tab_spectrum += 2.0*tab_mu[i]*tab_T_old*tab_g[i]
        tab_T, tab_T_old = tab_T_old, tab_T
    timing.SPECTRUM_TIME += (timeit.default_timer() - start_spectrum_time)
    timing.SPECTRUM_NOPS += 7.0*self.n_pts*n_kpm
    return 2.0*tab_spectrum/(np.pi*np.sqrt(1.0-self.tab_x**2)*(self.e_max-self.e_min+2.0*self.e_resolution))


@numba_decorator
def compute_spectral_function_from_mu(n_kpm,tab_T,tab_T_old,tab_x,tab_mu,tab_g,tab_spectrum):
  for i in range(2,n_kpm+1):
    tab_T_old = 2.0*tab_x*tab_T-tab_T_old
    tab_spectrum += 2.0*tab_mu[i]*tab_T_old*tab_g[i]
    tab_T, tab_T_old = tab_T_old, tab_T
  return tab_spectrum


def gpe_evolution(i_seed, geometry, initial_state, H, propagation, measurement, timing, debug=False, spectral_function=None):

  def solout(t,y):
    timing.N_SOLOUT+=1
#    print(t,timing.N_SOLOUT)
    return None

#  print('Inside GPE build_disorder = ',build_disorder)
# print('0',initial_state.type)
  start_dummy_time=timeit.default_timer()
#  dimension = H.dimension
#  tab_dim = geometry.tab_dim
  tab_extended_dim = geometry.tab_extended_dim
#  tab_delta = geometry.tab_delta
  hs_dim = geometry.hs_dim
  accuracy = propagation.accuracy
  if H.randomize_hamiltonian or H.seed==0:
    if geometry.reproducible_randomness:
      seed = i_seed+1234+H.custom_seed
    else:
      seed = None
#      print(i_seed,seed)
    H.generate_disorder(seed)
    measurement.perform_measurement_potential(H)
 #      H.energy_range(accurate=propagation.accurate_bounds)
#  print(initial_state.randomize_initial_state)
  if initial_state.randomize_initial_state or initial_state.seed==0:
    if geometry.reproducible_randomness:
      seed = i_seed+2345+H.custom_seed
    else:
      seed = None
    initial_state.prepare_initial_state(seed)
  psi = Wavefunction(geometry)
  timing.DUMMY_TIME+=(timeit.default_timer() - start_dummy_time)
  if propagation.method=='che':
    H.energy_range(accurate=propagation.accurate_bounds)
#    H.energy_range(accurate=True)
#    print('  accurate bounds',H.e_min,H.e_max)
#    H.energy_range(accurate=False)
#  print('inaccurate bounds',H.e_min,H.e_max)
#  if build_initial_state:
#     print('multi_point initial state, randomized')
#     anderson.wavefunction.Wavefunction.prepare_initial_state(initial_state,seed=i_seed+2345)
#     print(initial_state.wfc.ravel()[0])
  if propagation.data_layout=='real':
    y = np.concatenate((np.real(initial_state.wfc.ravel()),np.imag(initial_state.wfc.ravel())))
  else:
    if propagation.method=='ode':
      y = initial_state.wfc.view(np.float64).ravel()
    else:
      y = np.copy(initial_state.wfc.ravel())
#  print(initial_state.wfc[0],initial_state.wfc[1])
#  print(timeit.default_timer())
#  timing.DUMMY_TIME+=(timeit.default_timer() - start_dummy_time)
  if (propagation.method=='ode'):
    rhs = np.zeros(2*hs_dim)
#    print('y',y.dtype,y.shape)
#    print('rhs',rhs.dtype,rhs.shape)
    solver = ode(f=lambda t,y: gross_pitaevskii(t,y,H,propagation.data_layout,rhs,timing)).set_integrator('dop853', atol=accuracy, rtol=10.0*accuracy, nsteps=10000)
#    solver.set_solout(solout)
    solver.set_initial_value(y)
#    print('After initialisation, N_SOLOUT = ',timing.N_SOLOUT)

#  print(timeit.default_timer())
  timing.DUMMY_TIME+=(timeit.default_timer() - start_dummy_time)

  start_expect_time = timeit.default_timer()
# Keeping the initial state is needed when the autocorrelation <psi(0)|psi(t)> is measured
  if measurement.measure_autocorrelation or measurement.measure_overlap:
    init_state_autocorr = copy.deepcopy(initial_state)
  else:
    init_state_autocorr = None
  measurement.perform_measurement_dispersion(0, H, initial_state, initial_state)
  timing.EXPECT_TIME+=(timeit.default_timer() - start_expect_time)
#  print('2',initial_state.wfc[0],initial_state.wfc[1])

  j_dispersion=0
  j_density=0
  j_spectral_function=0
#      print('3',psi.wfc.shape,psi.wfc.dtype,y.shape,y.dtype)
  if propagation.data_layout=='real':
# The following two lines are faster than the natural implementation psi.wfc= y[0:dim_x]+1j*y[dim_x:2*dim_x]
    psi.wfc.real=y[0:hs_dim].reshape(tab_extended_dim)
    psi.wfc.imag=y[hs_dim:2*hs_dim].reshape(tab_extended_dim)
  else:
#        print( y.view(np.complex128).shape)
    psi.wfc[:] = y.view(np.complex128).reshape(tab_extended_dim)[:]
  if measurement.tab_time[0,2]== 1:
 #   print('It is time to store density',measurement.tab_time[0,0],j_density)
    measurement.perform_measurement_density(j_density,psi)
    j_density+=1
  if measurement.tab_time[0,3]==1:
#    print('Measure spectral function at time:',measurement.tab_time[0,0],j_spectral_function)
#        print('It is time to store density',measurement.tab_time[i,0],j_density)
    measurement.tab_spectrum[:,j_spectral_function] = spectral_function.compute_spectral_function(\
      i_seed, geometry, initial_state, H, timing, build_disorder=False, build_initial_state=False)
#    print('j_spectral_function = ',j_spectral_function)
    j_spectral_function+=1
  delta_t_old = -1.0
  tiny = 1.e-12
#time evolution
#  print(measurement.tab_time)
  for i in range(1,measurement.tab_time.shape[0]):
    if (propagation.method == 'ode'):
      start_ode_time = timeit.default_timer()
      solver.integrate(measurement.tab_time[i,0])
#      print(i,measurement.tab_time[i,0],timing.N_SOLOUT)
      timing.ODE_TIME+=(timeit.default_timer() - start_ode_time)
    else:
      start_che_time = timeit.default_timer()
      delta_t=measurement.tab_time[i,0]-measurement.tab_time[i-1,0]
      if abs(delta_t-delta_t_old)>tiny:
# time step has changed
# recompute the coefficients of the Chebyshev series
#      print('Recompute Chebyshev coefficients for delta_t = ',delta_t)
        propagation.delta_t = delta_t
        propagation.script_delta_t = 0.5*propagation.delta_t*(H.e_max-H.e_min)
        propagation.compute_chebyshev_coefficients(accuracy,timing)
      delta_t_old=delta_t
#      print(i_prop,start_che_time)
#      print(timing.MAX_NONLINEAR_PHASE)
      propagation.chebyshev_propagation(y, H, propagation,timing)
#      print(np.vdot(y,y)*H.delta_vol)
#      print(timing.MAX_NONLINEAR_PHASE)
#      print(y[2000])
      timing.CHE_TIME+=(timeit.default_timer() - start_che_time)
      timing.CHE_NOPS+=(12.0+7.0*H.dimension)*hs_dim*propagation.tab_coef.size
#      print(y[0])
    if measurement.tab_time[i,1]==1 or measurement.tab_time[i,2]==1:
      start_dummy_time=timeit.default_timer()
      if (propagation.method == 'ode'): y=solver.y
#      print('3',psi.wfc.shape,psi.wfc.dtype,y.shape,y.dtype)
      if propagation.data_layout=='real':
# The following two lines are faster than the natural implementation psi.wfc= y[0:dim_x]+1j*y[dim_x:2*dim_x]
        psi.wfc.real=y[0:hs_dim].reshape(tab_extended_dim)
        psi.wfc.imag=y[hs_dim:2*hs_dim].reshape(tab_extended_dim)
      else:
#        print( y.view(np.complex128).shape)
        psi.wfc[:] = y.view(np.complex128).reshape(tab_extended_dim)[:]
#      print('4',psi.wfc.shape,psi.wfc.dtype)
      timing.DUMMY_TIME+=(timeit.default_timer() - start_dummy_time)
      start_expect_time = timeit.default_timer()
      if measurement.tab_time[i,1]==1:

        j_dispersion+=1
        measurement.perform_measurement_dispersion(j_dispersion, H, psi, init_state_autocorr)
      if measurement.tab_time[i,2]==1:
#        print('It is time to store density',measurement.tab_time[i,0],j_density)
        measurement.perform_measurement_density(j_density, psi)
        j_density+=1
      timing.EXPECT_TIME+=(timeit.default_timer() - start_expect_time)
      if measurement.tab_time[i,3]==1:
#        print('Measure spectral function at time:',measurement.tab_time[i,0],j_spectral_function)
#        print('It is time to store density',measurement.tab_time[i,0],j_density)
#        print(j_spectral_function,psi.wfc[0])
#        print(propagation_spectral.delta_t,propagation_spectral.t_max)
        measurement.tab_spectrum[:,j_spectral_function] = spectral_function.compute_spectral_function(\
          i_seed, geometry, psi, H, timing, build_disorder=False, build_initial_state=False)
#        print(j_spectral_function,psi.wfc[0])
#        print('j_spectral_function = ',j_spectral_function)
        j_spectral_function+=1
  measurement.perform_measurement_final(psi, init_state_autocorr)
#     i_tab+=1
#    print('3',initial_state.wfc[0],initial_state.wfc[1])
#  if not no_init:
#    measurement.tab_spectrum[:] = anderson.propagation.compute_spectral_function(i_seed, geometry, initial_state, H, propagation, measurement_spectral, spectral_function, timing)
  return


"""
def apply_minus_i_h_gpe_complex(wfc, H, rhs):
  dim_x = H.dim_x
  if (H.interaction == 0.0):
    H.diagonal_term=H.disorder
  else:
    H.diagonal_term=H.disorder+H.interaction*(np.abs(wfc)**2)
  if H.boundary_condition=='periodic':
    rhs[0]       = 1j * (H.tunneling * (wfc[dim_x-1] + wfc[1]) - H.diagonal_term[0] * wfc[0])
    rhs[dim_x-1] = 1j * (H.tunneling * (wfc[dim_x-2] + wfc[0]) - H.diagonal_term[dim_x-1] * wfc[dim_x-1])
  else:
    rhs[0]       = 1j * (H.tunneling * wfc[1]       - H.diagonal_term[0]       * wfc[0])
    rhs[dim_x-1] = 1j * (H.tunneling * wfc[dim_x-2] - H.diagonal_term[dim_x-1] * wfc[dim_x-1])
  rhs[1:dim_x-1] = 1j * (H.tunneling * (wfc[0:dim_x-2] + wfc[2:dim_x]) - H.diagonal_term[1:dim_x-1] * wfc[1:dim_x-1])
  return rhs

def apply_minus_i_h_gpe_real(wfc, H, rhs):
  dim_x = H.dim_x
  if (H.interaction == 0.0):
    H.diagonal_term=H.disorder
  else:
    H.diagonal_term=H.disorder+H.interaction*(wfc[0:dim_x]**2+wfc[dim_x:2*dim_x]**2)
  if H.boundary_condition=='periodic':
    rhs[0]         = -H.tunneling * (wfc[2*dim_x-1] + wfc[dim_x+1]) + H.diagonal_term[0]       * wfc[dim_x]
    rhs[dim_x]     =  H.tunneling * (wfc[dim_x-1]   + wfc[1])       - H.diagonal_term[0]       * wfc[0]
    rhs[dim_x-1]   = -H.tunneling * (wfc[2*dim_x-2] + wfc[dim_x])   + H.diagonal_term[dim_x-1] * wfc[2*dim_x-1]
    rhs[2*dim_x-1] =  H.tunneling * (wfc[dim_x-2]   + wfc[0])       - H.diagonal_term[dim_x-1] * wfc[dim_x-1]
  else:
    rhs[0]         = -H.tunneling *  wfc[dim_x+1]   + H.diagonal_term[0]       * wfc[dim_x]
    rhs[dim_x]     =  H.tunneling *  wfc[1]         - H.diagonal_term[0]       * wfc[0]
    rhs[dim_x-1]   = -H.tunneling *  wfc[2*dim_x-2] + H.diagonal_term[dim_x-1] * wfc[2*dim_x-1]
    rhs[2*dim_x-1] =  H.tunneling *  wfc[dim_x-2]   - H.diagonal_term[dim_x-1] * wfc[dim_x-1]
  rhs[1:dim_x-1]         = -H.tunneling * (wfc[dim_x:2*dim_x-2] + wfc[dim_x+2:2*dim_x]) + H.diagonal_term[1:dim_x-1]*wfc[dim_x+1:2*dim_x-1]
  rhs[dim_x+1:2*dim_x-1] =  H.tunneling * (wfc[0:dim_x-2]       + wfc[2:dim_x])         - H.diagonal_term[1:dim_x-1]*wfc[1:dim_x-1]
  return rhs

def elementary_clenshaw_step_complex_old(wfc, H, psi, psi_old, c_coef, one_or_two, add_real):
#  print('wfc',wfc.shape,wfc.dtype)
#  print('psi',psi.shape,psi.dtype)
#  print('psi_old',psi_old.shape,psi_old.dtype)
#  print('in',wfc[0],psi[0],psi_old[0],c_coef,one_or_two,add_real)
  use_sparse = False
  if H.dimension > 1:
    use_sparse = True
#  print(use_sparse)
  if use_sparse:
    if add_real:
      psi_old[:] = one_or_two*(H.two_over_delta_e*H.sparse_matrix.dot(psi[:])-H.two_e0_over_delta_e*psi[:])+c_coef*wfc[:]-psi_old[:]
    else:
      psi_old[:] = one_or_two*(H.two_over_delta_e*H.sparse_matrix.dot(psi[:])-H.two_e0_over_delta_e*psi[:])+1j*c_coef*wfc[:]-psi_old[:]
  else:
    dim_x = H.tab_dim[0]
    if add_real:
      if H.tab_boundary_condition[0]=='periodic':
        psi_old[0] = one_or_two*((H.two_over_delta_e*H.disorder[0]-H.two_e0_over_delta_e)*psi[0]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[1]+psi[dim_x-1]))+c_coef*wfc[0]-psi_old[0]
        psi_old[dim_x-1] = one_or_two*((H.two_over_delta_e*H.disorder[dim_x-1]-H.two_e0_over_delta_e)*psi[dim_x-1]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[0]+psi[dim_x-2]))+c_coef*wfc[dim_x-1]-psi_old[dim_x-1]
      else:
        psi_old[0] = one_or_two*((H.two_over_delta_e*H.disorder[0]-H.two_e0_over_delta_e)*psi[0]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[1]))+c_coef*wfc[0]-psi_old[0]
        psi_old[dim_x-1] = one_or_two*((H.two_over_delta_e*H.disorder[dim_x-1]-H.two_e0_over_delta_e)*psi[dim_x-1]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[dim_x-2]))+c_coef*wfc[dim_x-1]-psi_old[dim_x-1]

      psi_old[1:dim_x-1] = one_or_two*((H.two_over_delta_e*H.disorder[1:dim_x-1]-H.two_e0_over_delta_e)*psi[1:dim_x-1]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[2:dim_x]+psi[0:dim_x-2]))+c_coef*wfc[1:dim_x-1]-psi_old[1:dim_x-1]
    else:
      if H.tab_boundary_condition[0]=='periodic':
        psi_old[0] = one_or_two*((H.two_over_delta_e*H.disorder[0]-H.two_e0_over_delta_e)*psi[0]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[1]+psi[dim_x-1]))+1j*c_coef*wfc[0]-psi_old[0]
        psi_old[dim_x-1] = one_or_two*((H.two_over_delta_e*H.disorder[dim_x-1]-H.two_e0_over_delta_e)*psi[dim_x-1]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[0]+psi[dim_x-2]))+1j*c_coef*wfc[dim_x-1]-psi_old[dim_x-1]
      else:
        psi_old[0] = one_or_two*((H.two_over_delta_e*H.disorder[0]-H.two_e0_over_delta_e)*psi[0]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[1]))+1j*c_coef*wfc[0]-psi_old[0]
        psi_old[dim_x-1] = one_or_two*((H.two_over_delta_e*H.disorder[dim_x-1]-H.two_e0_over_delta_e)*psi[dim_x-1]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[dim_x-2]))+1j*c_coef*wfc[dim_x-1]-psi_old[dim_x-1]
      psi_old[1:dim_x-1] = one_or_two*((H.two_over_delta_e*H.disorder[1:dim_x-1]-H.two_e0_over_delta_e)*psi[1:dim_x-1]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[2:dim_x]+psi[0:dim_x-2]))+1j*c_coef*wfc[1:dim_x-1]-psi_old[1:dim_x-1]
#  print('out',wfc[0],psi[0],psi_old[0])
  return

def elementary_clenshaw_step_real_old(wfc, H, psi, psi_old, c_coef, one_or_two, add_real):
#  print('wfc',wfc.shape,wfc.dtype)
#  print('psi',psi.shape,psi.dtype)
#  print('psi_old',psi_old.shape,psi_old.dtype)
#  print('in',wfc[0],psi[0],psi_old[0],c_coef,one_or_two,add_real)
  use_sparse = False
  if H.dimension > 1:
    use_sparse = True
  if use_sparse:
    ntot = H.ntot
    if add_real:
      psi_old[0:ntot] = one_or_two*(H.two_over_delta_e*H.sparse_matrix.dot(psi[0:ntot])-H.two_e0_over_delta_e*psi[0:ntot])+c_coef*wfc[0:ntot]-psi_old[0:ntot]
      psi_old[ntot:2*ntot] = one_or_two*(H.two_over_delta_e*H.sparse_matrix.dot(psi[ntot:2*ntot])-H.two_e0_over_delta_e*psi[ntot:2*ntot])+c_coef*wfc[ntot:2*ntot]-psi_old[ntot:2*ntot]
    else:
      psi_old[0:ntot] = one_or_two*(H.two_over_delta_e*H.sparse_matrix.dot(psi[0:ntot])-H.two_e0_over_delta_e*psi[0:ntot])-c_coef*wfc[ntot:2*ntot]-psi_old[0:ntot]
      psi_old[ntot:2*ntot] = one_or_two*(H.two_over_delta_e*H.sparse_matrix.dot(psi[ntot:2*ntot])-H.two_e0_over_delta_e*psi[ntot:2*ntot])+c_coef*wfc[0:ntot]-psi_old[ntot:2*ntot]
  else:
    dim_x = H.tab_dim[0]
    if add_real:
      if H.tab_boundary_condition[0]=='periodic':
        psi_old[0] = one_or_two*((H.two_over_delta_e*H.disorder[0]-H.two_e0_over_delta_e)*psi[0]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[1]+psi[dim_x-1]))+c_coef*wfc[0]-psi_old[0]
        psi_old[dim_x] = one_or_two*((H.two_over_delta_e*H.disorder[0]-H.two_e0_over_delta_e)*psi[dim_x]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[dim_x+1]+psi[2*dim_x-1]))+c_coef*wfc[dim_x]-psi_old[dim_x]
        psi_old[dim_x-1] = one_or_two*((H.two_over_delta_e*H.disorder[dim_x-1]-H.two_e0_over_delta_e)*psi[dim_x-1]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[0]+psi[dim_x-2]))+c_coef*wfc[dim_x-1]-psi_old[dim_x-1]
        psi_old[2*dim_x-1] = one_or_two*((H.two_over_delta_e*H.disorder[dim_x-1]-H.two_e0_over_delta_e)*psi[2*dim_x-1]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[dim_x]+psi[2*dim_x-2]))+c_coef*wfc[2*dim_x-1]-psi_old[2*dim_x-1]
      else:
        psi_old[0] = one_or_two*((H.two_over_delta_e*H.disorder[0]-H.two_e0_over_delta_e)*psi[0]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[1]))+c_coef*wfc[0]-psi_old[0]
        psi_old[dim_x] = one_or_two*((H.two_over_delta_e*H.disorder[0]-H.two_e0_over_delta_e)*psi[dim_x]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[dim_x+1]))+c_coef*wfc[dim_x]-psi_old[dim_x]
        psi_old[dim_x-1] = one_or_two*((H.two_over_delta_e*H.disorder[dim_x-1]-H.two_e0_over_delta_e)*psi[dim_x-1]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[dim_x-2]))+c_coef*wfc[dim_x-1]-psi_old[dim_x-1]
        psi_old[2*dim_x-1] = one_or_two*((H.two_over_delta_e*H.disorder[dim_x-1]-H.two_e0_over_delta_e)*psi[2*dim_x-1]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[2*dim_x-2]))+c_coef*wfc[2*dim_x-1]-psi_old[2*dim_x-1]
      psi_old[1:dim_x-1] = one_or_two*((H.two_over_delta_e*H.disorder[1:dim_x-1]-H.two_e0_over_delta_e)*psi[1:dim_x-1]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[2:dim_x]+psi[0:dim_x-2]))+c_coef*wfc[1:dim_x-1]-psi_old[1:dim_x-1]
      psi_old[dim_x+1:2*dim_x-1] = one_or_two*((H.two_over_delta_e*H.disorder[1:dim_x-1]-H.two_e0_over_delta_e)*psi[dim_x+1:2*dim_x-1]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[dim_x+2:2*dim_x]+psi[dim_x:2*dim_x-2]))+c_coef*wfc[dim_x+1:2*dim_x-1]-psi_old[dim_x+1:2*dim_x-1]
    else:
      if H.tab_boundary_condition[0]=='periodic':
        psi_old[0] = one_or_two*((H.two_over_delta_e*H.disorder[0]-H.two_e0_over_delta_e)*psi[0]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[1]+psi[dim_x-1]))-c_coef*wfc[dim_x]-psi_old[0]
        psi_old[dim_x] = one_or_two*((H.two_over_delta_e*H.disorder[0]-H.two_e0_over_delta_e)*psi[dim_x]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[dim_x+1]+psi[2*dim_x-1]))+c_coef*wfc[0]-psi_old[dim_x]
        psi_old[dim_x-1] = one_or_two*((H.two_over_delta_e*H.disorder[dim_x-1]-H.two_e0_over_delta_e)*psi[dim_x-1]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[0]+psi[dim_x-2]))-c_coef*wfc[2*dim_x-1]-psi_old[dim_x-1]
        psi_old[2*dim_x-1] = one_or_two*((H.two_over_delta_e*H.disorder[dim_x-1]-H.two_e0_over_delta_e)*psi[2*dim_x-1]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[dim_x]+psi[2*dim_x-2]))+c_coef*wfc[dim_x-1]-psi_old[2*dim_x-1]
      else:
        psi_old[0] = one_or_two*((H.two_over_delta_e*H.disorder[0]-H.two_e0_over_delta_e)*psi[0]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[1]))-c_coef*wfc[dim_x]-psi_old[0]
        psi_old[dim_x] = one_or_two*((H.two_over_delta_e*H.disorder[0]-H.two_e0_over_delta_e)*psi[dim_x]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[dim_x+1]))+c_coef*wfc[0]-psi_old[dim_x]
        psi_old[dim_x-1] = one_or_two*((H.two_over_delta_e*H.disorder[dim_x-1]-H.two_e0_over_delta_e)*psi[dim_x-1]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[dim_x-2]))-c_coef*wfc[2*dim_x-1]-psi_old[dim_x-1]
        psi_old[2*dim_x-1] = one_or_two*((H.two_over_delta_e*H.disorder[dim_x-1]-H.two_e0_over_delta_e)*psi[2*dim_x-1]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[2*dim_x-2]))+c_coef*wfc[dim_x-1]-psi_old[2*dim_x-1]
      psi_old[1:dim_x-1] = one_or_two*((H.two_over_delta_e*H.disorder[1:dim_x-1]-H.two_e0_over_delta_e)*psi[1:dim_x-1]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[2:dim_x]+psi[0:dim_x-2]))-c_coef*wfc[dim_x+1:2*dim_x-1]-psi_old[1:dim_x-1]
      psi_old[dim_x+1:2*dim_x-1] = one_or_two*((H.two_over_delta_e*H.disorder[1:dim_x-1]-H.two_e0_over_delta_e)*psi[dim_x+1:2*dim_x-1]-H.two_over_delta_e*H.tab_tunneling[0]*(psi[dim_x+2:2*dim_x]+psi[dim_x:2*dim_x-2]))+c_coef*wfc[1:dim_x-1]-psi_old[dim_x+1:2*dim_x-1]
#  print('no_cffi psi_old',psi_old[dim_x],psi_old[dim_x+1],psi_old[2*dim_x-2],psi_old[2*dim_x-1])
#  print('no_cffi psi    ',psi[dim_x],psi[dim_x+1],psi[2*dim_x-2],psi[2*dim_x-1])
#  print('no_cffi wfc    ',wfc[dim_x],wfc[dim_x+1],wfc[2*dim_x-2],wfc[2*dim_x-1])
#  print('no_cffi wfc_dec',wfc[0],wfc[1],wfc[dim_x-2],wfc[dim_x-1])
# ,H.two_over_delta_e,H.two_e0_over_delta_e,H.tab_tunneling[0],c_coef,one_or_two,add_real)
  return

def elementary_clenshaw_step_complex(wfc, H, psi, psi_old, c_coef, add_real, c1, c2, tab_c3):
#  print('wfc',wfc.shape,wfc.dtype)
#  print('psi',psi.shape,psi.dtype)
#  print('psi_old',psi_old.shape,psi_old.dtype)
#  print('disorder',H.disorder.shape)
#  print('in',wfc[0],psi[0],psi_old[0],c_coef,one_or_two,add_real)
  if not(add_real):
    c_coef*=1j
# Generic code uses the sparse multiplication
#  if not H.multiply_has_specific_routine:
  if True:
#    print(psi.shape,psi_old.shape,wfc.shape,H.sparse_matrix.dot(psi[:]).shape)
#    psi_old[:] = c1*H.sparse_matrix.dot(psi[:])-c2*psi[:]+c_coef*wfc[:]-psi_old[:]
    psi_old[:] = c1*H.apply_h(psi)-c2*psi[:]+c_coef*wfc[:]-psi_old[:]
  else:
# Specific code for dimension 1
    if H.dimension==1:
      c3=tab_c3[0]
      dim_x = H.tab_dim[0]
      if H.tab_boundary_condition[0]=='periodic':
        psi_old[0]       = (c1*H.disorder[0]-c2)      *psi[0]      -c3*(psi[1]+psi[dim_x-1])+c_coef*wfc[0]      -psi_old[0]
        psi_old[dim_x-1] = (c1*H.disorder[dim_x-1]-c2)*psi[dim_x-1]-c3*(psi[0]+psi[dim_x-2])+c_coef*wfc[dim_x-1]-psi_old[dim_x-1]
      else:
        psi_old[0]       = (c1*H.disorder[0]-c2)      *psi[0]      -c3*(psi[1])      +c_coef*wfc[0]      -psi_old[0]
        psi_old[dim_x-1] = (c1*H.disorder[dim_x-1]-c2)*psi[dim_x-1]-c3*(psi[dim_x-2])+c_coef*wfc[dim_x-1]-psi_old[dim_x-1]
      psi_old[1:dim_x-1] = (c1*H.disorder[1:dim_x-1]-c2)*psi[1:dim_x-1]-c3*(psi[2:dim_x]+psi[0:dim_x-2])+c_coef*wfc[1:dim_x-1]-psi_old[1:dim_x-1]
# Specific code for dimension 2
    if H.dimension==2:
      c3_x=tab_c3[0]
      c3_y=tab_c3[1]
      dim_x = H.tab_dim[0]
      dim_y = H.tab_dim[1]
      b_x = H.tab_boundary_condition[0]
      b_y = H.tab_boundary_condition[1]
# The code propagates along the x axis, computing one vector (along y) at each iteration
# To decrase the number of memory accesses, 3 temporary vectors are used, containing the current x row, the previous and the next rows
# To simplify the code, the temporary vectors have 2 additional components, set to zero for fixed boundary conditions and to the wrapped values for periodic boundary conditions
# Create the 3 temporary vectors
      p_old=np.zeros(dim_y+2,dtype=np.complex128)
      p_current=np.zeros(dim_y+2,dtype=np.complex128)
      p_new=np.zeros(dim_y+2,dtype=np.complex128)
# If periodic boundary conditions along x, initialize p_current to the last row, otherwise 0
      if b_x=='periodic':
        p_current[1:dim_y+1]=psi[(dim_x-1)*dim_y:dim_x*dim_y]
# Initialize the next row, which will become the current row in the first iteration of the loop
      p_new[1:dim_y+1]=psi[0:dim_y]
# If periodic boundary condition along y, copy the first and last components
      if b_y=='periodic':
        p_new[0]=p_new[dim_y]
        p_new[dim_y+1]=p_new[1]
      for i in range(dim_x):
        p_temp=p_old
        p_old=p_current
        p_current=p_new
        p_new=p_temp
        if i<dim_x-1:
# The generic row
          p_new[1:dim_y+1]=psi[(i+1)*dim_y:(i+2)*dim_y]
        else:
# If in last row, put in p_new the first row if periodic along x, 0 otherwise )
          if b_x=='periodic':
            p_new[1:dim_y+1]=psi[0:dim_y]
          else:
            p_new[1:dim_y+1]=0.0
# If periodic boundary condition along y, copy the first and last components
        if b_y=='periodic':
          p_new[0]=p_new[dim_y]
          p_new[dim_y+1]=p_new[1]
        i_low=i*dim_y
        i_high=i_low+dim_y
# Ready to treat the current row
#        psi_old[i*dim_y:(i+1)*dim_y] = (c1*H.disorder[i,0:dim_y]-c2)*p_current[1:dim_y+1] - c3_y*(p_current[2:dim_y+2]+ p_current[0:dim_y]) - c3_x*(p_old[1:dim_y+1]+p_new[1:dim_y+1]) + c_coef*wfc[i*dim_y:(i+1)*dim_y] - psi_old[i*dim_y:(i+1)*dim_y]
        psi_old[i_low:i_high] = (c1*H.disorder[i,0:dim_y]-c2)*p_current[1:dim_y+1] - c3_y*(p_current[2:dim_y+2]+ p_current[0:dim_y]) - c3_x*(p_old[1:dim_y+1]+p_new[1:dim_y+1]) + c_coef*wfc[i_low:i_high] - psi_old[i_low:i_high]
  return

def elementary_clenshaw_step_real(wfc, H, psi, psi_old, c_coef, add_real, c1, c2, tab_c3):
#  print('wfc',wfc.shape,wfc.dtype)
#  print('psi',psi.shape,psi.dtype)
#  print('psi_old',psi_old.shape,psi_old.dtype)
#  print('in',wfc[0],psi[0],psi_old[0],c_coef,one_or_two,add_real)
  use_sparse = False
  if H.dimension > 2:
    use_sparse = True
  if use_sparse:
    ntot = H.ntot
    if add_real:
      psi_old[0:ntot] = c1*H.sparse_matrix.dot(psi[0:ntot])-c2*psi[0:ntot]+c_coef*wfc[0:ntot]-psi_old[0:ntot]
      psi_old[ntot:2*ntot] = c1*H.sparse_matrix.dot(psi[ntot:2*ntot])-c2*psi[ntot:2*ntot]+c_coef*wfc[ntot:2*ntot]-psi_old[ntot:2*ntot]
    else:
      psi_old[0:ntot] = c1*H.sparse_matrix.dot(psi[0:ntot])-c2*psi[0:ntot]-c_coef*wfc[ntot:2*ntot]-psi_old[0:ntot]
      psi_old[ntot:2*ntot] = c1*H.sparse_matrix.dot(psi[ntot:2*ntot])-c2*psi[ntot:2*ntot]+c_coef*wfc[0:ntot]-psi_old[ntot:2*ntot]
  else:
# Specific code for dimension 1
    if H.dimension==1:
      c3=tab_c3[0]
      dim_x = H.tab_dim[0]
      if add_real:
        if H.tab_boundary_condition[0]=='periodic':
          psi_old[0] = (c1*H.disorder[0]-c2)*psi[0]-c3*(psi[1]+psi[dim_x-1])+c_coef*wfc[0]-psi_old[0]
          psi_old[dim_x] = (c1*H.disorder[0]-c2)*psi[dim_x]-c3*(psi[dim_x+1]+psi[2*dim_x-1])+c_coef*wfc[dim_x]-psi_old[dim_x]
          psi_old[dim_x-1] = (c1*H.disorder[dim_x-1]-c2)*psi[dim_x-1]-c3*(psi[0]+psi[dim_x-2])+c_coef*wfc[dim_x-1]-psi_old[dim_x-1]
          psi_old[2*dim_x-1] = (c1*H.disorder[dim_x-1]-c2)*psi[2*dim_x-1]-c3*(psi[dim_x]+psi[2*dim_x-2])+c_coef*wfc[2*dim_x-1]-psi_old[2*dim_x-1]
        else:
          psi_old[0] = (c1*H.disorder[0]-c2)*psi[0]-c3*(psi[1])+c_coef*wfc[0]-psi_old[0]
          psi_old[dim_x] = (c1*H.disorder[0]-c2)*psi[dim_x]-c3*(psi[dim_x+1])+c_coef*wfc[dim_x]-psi_old[dim_x]
          psi_old[dim_x-1] = (c1*H.disorder[dim_x-1]-c2)*psi[dim_x-1]-c3*(psi[dim_x-2])+c_coef*wfc[dim_x-1]-psi_old[dim_x-1]
          psi_old[2*dim_x-1] = (c1*H.disorder[dim_x-1]-c2)*psi[2*dim_x-1]-c3*(psi[2*dim_x-2])+c_coef*wfc[2*dim_x-1]-psi_old[2*dim_x-1]
        psi_old[1:dim_x-1] = (c1*H.disorder[1:dim_x-1]-c2)*psi[1:dim_x-1]-c3*(psi[2:dim_x]+psi[0:dim_x-2])+c_coef*wfc[1:dim_x-1]-psi_old[1:dim_x-1]
        psi_old[dim_x+1:2*dim_x-1] = (c1*H.disorder[1:dim_x-1]-c2)*psi[dim_x+1:2*dim_x-1]-c3*(psi[dim_x+2:2*dim_x]+psi[dim_x:2*dim_x-2])+c_coef*wfc[dim_x+1:2*dim_x-1]-psi_old[dim_x+1:2*dim_x-1]
      else:
        if H.tab_boundary_condition[0]=='periodic':
          psi_old[0] = (c1*H.disorder[0]-c2)*psi[0]-c3*(psi[1]+psi[dim_x-1])-c_coef*wfc[dim_x]-psi_old[0]
          psi_old[dim_x] = (c1*H.disorder[0]-c2)*psi[dim_x]-c3*(psi[dim_x+1]+psi[2*dim_x-1])+c_coef*wfc[0]-psi_old[dim_x]
          psi_old[dim_x-1] = (c1*H.disorder[dim_x-1]-c2)*psi[dim_x-1]-c3*(psi[0]+psi[dim_x-2])-c_coef*wfc[2*dim_x-1]-psi_old[dim_x-1]
          psi_old[2*dim_x-1] = (c1*H.disorder[dim_x-1]-c2)*psi[2*dim_x-1]-c3*(psi[dim_x]+psi[2*dim_x-2])+c_coef*wfc[dim_x-1]-psi_old[2*dim_x-1]
        else:
          psi_old[0] = (c1*H.disorder[0]-c2)*psi[0]-c3*(psi[1])-c_coef*wfc[dim_x]-psi_old[0]
          psi_old[dim_x] = (c1*H.disorder[0]-c2)*psi[dim_x]-c3*(psi[dim_x+1])+c_coef*wfc[0]-psi_old[dim_x]
          psi_old[dim_x-1] = (c1*H.disorder[dim_x-1]-c2)*psi[dim_x-1]-c3*(psi[dim_x-2])-c_coef*wfc[2*dim_x-1]-psi_old[dim_x-1]
          psi_old[2*dim_x-1] = (c1*H.disorder[dim_x-1]-c2)*psi[2*dim_x-1]-c3*(psi[2*dim_x-2])+c_coef*wfc[dim_x-1]-psi_old[2*dim_x-1]
        psi_old[1:dim_x-1] = (c1*H.disorder[1:dim_x-1]-c2)*psi[1:dim_x-1]-c3*(psi[2:dim_x]+psi[0:dim_x-2])-c_coef*wfc[dim_x+1:2*dim_x-1]-psi_old[1:dim_x-1]
        psi_old[dim_x+1:2*dim_x-1] = (c1*H.disorder[1:dim_x-1]-c2)*psi[dim_x+1:2*dim_x-1]-c3*(psi[dim_x+2:2*dim_x]+psi[dim_x:2*dim_x-2])+c_coef*wfc[1:dim_x-1]-psi_old[dim_x+1:2*dim_x-1]
# Specific code for dimension 2
    if H.dimension==2:
      c3_x=tab_c3[0]
      c3_y=tab_c3[1]
      dim_x = H.tab_dim[0]
      dim_y = H.tab_dim[1]
      ntot = dim_x*dim_y
      b_x = H.tab_boundary_condition[0]
      b_y = H.tab_boundary_condition[1]
# The code propagates along the x axis, computing one vector (along y) at each iteration
# To decrase the number of memory accesses, 3 temporary vectors are used, containing the current x row, the previous and the next rows
# To simplify the code, the temporary vectors have 2 additional components, set to zero for fixed boundary conditions and to the wrapped values for periodic boundary conditions
# Create the 3 temporary vectors
      p_old=np.zeros(2*dim_y+4)
      p_current=np.zeros(2*dim_y+4)
      p_new=np.zeros(2*dim_y+4)
# If periodic boundary conditions along x, initialize p_current to the last row, otherwise 0
      if b_x=='periodic':
        p_current[1:dim_y+1]=psi[(dim_x-1)*dim_y:dim_x*dim_y]
        p_current[dim_y+3:2*dim_y+3]=psi[ntot+(dim_x-1)*dim_y:ntot+dim_x*dim_y]
# Initialize the next row, which will become the current row in the first iteration of the loop
      p_new[1:dim_y+1]=psi[0:dim_y]
      p_new[dim_y+3:2*dim_y+3]=psi[ntot:ntot+dim_y]
# If periodic boundary condition along y, copy the first and last components
      if b_y=='periodic':
        p_new[0]=p_new[dim_y]
        p_new[dim_y+1]=p_new[1]
        p_new[dim_y+2]=p_new[2*dim_y+2]
        p_new[2*dim_y+3]=p_new[dim_y+3]
      for i in range(dim_x):
        p_temp=p_old
        p_old=p_current
        p_current=p_new
        p_new=p_temp
        if i<dim_x-1:
# The generic row
          p_new[1:dim_y+1]=psi[(i+1)*dim_y:(i+2)*dim_y]
          p_new[dim_y+3:2*dim_y+3]=psi[ntot+(i+1)*dim_y:ntot+(i+2)*dim_y]
        else:
# If in last row, put in p_new the first row if periodic along x, 0 otherwise )
          if b_x=='periodic':
            p_new[1:dim_y+1]=psi[0:dim_y]
            p_new[dim_y+3:2*dim_y+3]=psi[ntot:ntot+dim_y]
          else:
            p_new[1:2*dim_y+3]=0.0
# If periodic boundary condition along y, copy the first and last components
        if b_y=='periodic':
          p_new[0]=p_new[dim_y]
          p_new[dim_y+1]=p_new[1]
          p_new[dim_y+2]=p_new[2*dim_y+2]
          p_new[2*dim_y+3]=p_new[dim_y+3]
        i_low=i*dim_y
        i_high=i_low+dim_y
# Ready to treat the current row
#        psi_old[i*dim_y:(i+1)*dim_y] = (c1*H.disorder[i,0:dim_y]-c2)*p_current[1:dim_y+1] - c3_y*(p_current[2:dim_y+2]+ p_current[0:dim_y]) - c3_x*(p_old[1:dim_y+1]+p_new[1:dim_y+1]) + c_coef*wfc[i*dim_y:(i+1)*dim_y] - psi_old[i*dim_y:(i+1)*dim_y]
        if add_real:
          psi_old[i_low:i_high] = (c1*H.disorder[i,0:dim_y]-c2)*p_current[1:dim_y+1] - c3_y*(p_current[2:dim_y+2]+ p_current[0:dim_y]) - c3_x*(p_old[1:dim_y+1]+p_new[1:dim_y+1]) + c_coef*wfc[i_low:i_high] - psi_old[i_low:i_high]
          psi_old[ntot+i_low:ntot+i_high] = (c1*H.disorder[i,0:dim_y]-c2)*p_current[dim_y+3:2*dim_y+3] - c3_y*(p_current[dim_y+4:2*dim_y+4]+ p_current[dim_y+2:2*dim_y+2]) - c3_x*(p_old[dim_y+3:2*dim_y+3]+p_new[dim_y+3:2*dim_y+3]) + c_coef*wfc[ntot+i_low:ntot+i_high] - psi_old[ntot+i_low:ntot+i_high]
        else:
          psi_old[i_low:i_high] = (c1*H.disorder[i,0:dim_y]-c2)*p_current[1:dim_y+1] - c3_y*(p_current[2:dim_y+2]+ p_current[0:dim_y]) - c3_x*(p_old[1:dim_y+1]+p_new[1:dim_y+1]) - c_coef*wfc[ntot+i_low:ntot+i_high] - psi_old[i_low:i_high]
          psi_old[ntot+i_low:ntot+i_high] = (c1*H.disorder[i,0:dim_y]-c2)*p_current[dim_y+3:2*dim_y+3] - c3_y*(p_current[dim_y+4:2*dim_y+4]+ p_current[dim_y+2:2*dim_y+2]) - c3_x*(p_old[dim_y+3:2*dim_y+3]+p_new[dim_y+3:2*dim_y+3]) + c_coef*wfc[i_low:i_high] - psi_old[ntot+i_low:ntot+i_high]

#  print('no_cffi psi_old',psi_old[dim_x],psi_old[dim_x+1],psi_old[2*dim_x-2],psi_old[2*dim_x-1])
#  print('no_cffi psi    ',psi[dim_x],psi[dim_x+1],psi[2*dim_x-2],psi[2*dim_x-1])
#  print('no_cffi wfc    ',wfc[dim_x],wfc[dim_x+1],wfc[2*dim_x-2],wfc[2*dim_x-1])
#  print('no_cffi wfc_dec',wfc[0],wfc[1],wfc[dim_x-2],wfc[dim_x-1])
# ,H.two_over_delta_e,H.two_e0_over_delta_e,H.tab_tunneling[0],c_coef,one_or_two,add_real)
  return


def compute_spectral_function(i_seed, geometry, initial_state, H, propagation, measurement, spectral_function, timing, debug=False, build_disorder=True, build_initial_state=False):
#  print(H.interaction,spectral_function.multiplicative_factor_for_interaction)
# When computing the spectral function from the temporal autocorrelation, it is better to switch off the interaction, so that what is computed is <psi(t)|delta(E-H)|\psi(t)> without any non-linear term in the delta function
# When the initial state is a plane wave, \overline{|\psi(r,t)|^2} is simply g/V that is a constant shift in energy
#  print('inside compute_spectral_function')
#  print(H.disorder[0,0])
#  print(np.sum(H.disorder))
#  print('Inside compute_spectral_function build_disorder = ',build_disorder,' seed = ',i_seed+1234)
  if build_disorder:
    H.generate_disorder(seed=i_seed+1234)
    measurement.perform_measurement_potential(H)
    if propagation.method=='che':
      H.generate_sparse_matrix()
      H.energy_range(accurate=propagation.accurate_bounds)
  save_interaction = H.interaction
  save_disorder = copy.deepcopy(H.disorder)
  if build_initial_state:
    initial_state.prepare_initial_state(seed=i_seed+2345)
#  print(save_disorder)
#  save_disorder = H.disorder
  H.interaction = 0.0
  H.disorder = H.disorder + save_interaction*spectral_function.multiplicative_factor_for_interaction*(np.abs(initial_state.wfc)**2)
  if spectral_function.method_spectral_function == 'kpm':
    return compute_spectral_function_kpm_method(initial_state, H, spectral_function)
  initial_state_2 = copy.deepcopy(initial_state)
#  print('1',initial_state.type,initial_state_2.type)
#  print(H.disorder[0,0])
#  print(np.sum(H.disorder))
#  print(save_disorder.dtype,initial_state.wfc.dtype)
#  print(H.interaction)
#  print(propagation.delta_t,propagation.t_max)
#  print(initial_state_2.wfc-initial_state.wfc)
#  print(initial_state.wfc[0,0])
  gpe_evolution(i_seed, geometry, initial_state_2, H, propagation, propagation, measurement, timing, build_disorder=False, build_initial_state=build_initial_state)
#  print(initial_state_2.wfc-initial_state.wfc)
#  print(initial_state.wfc[0,0])
  H.interaction = save_interaction
  H.disorder = copy.deepcopy(save_disorder)
#  H.disorder = save_disorder
  initial_state = copy.deepcopy(initial_state_2)
#  print('2',initial_state.type,initial_state_2.type)
#  print(H.disorder[0,0])
#  print(np.sum(H.disorder))
#  print(H.interaction)
#  print(measurement.tab_autocorrelation)
#  measurement.tab_spectrum[:] = spectral_function.spectral_function_from_temporal_autocorrelation(measurement.tab_autocorrelation)
#  print(measurement.tab_spectrum)
  return spectral_function.spectral_function_from_temporal_autocorrelation(measurement.tab_autocorrelation)

  def spectral_function_from_temporal_autocorrelation(self,tab_autocorrelation):
# The autocorrelation function for negative time is simply the complex conjugate of the one at positive time
# We will use an inverse FFT, so that positive time must be first, followed by negative times (all increasing)
# see manual of numpy.fft.ifft for explanations
# The number of points in tab_autocorrelation is n_pts_autocorr+1
# Multiply by a complex oscillatory exponential so that the energy is shifted
    e_middle = 0.5*(self.e_max+self.e_min)
#    print(e_middle)
    tab_autocorrelation *= np.exp(1j*e_middle*self.delta_t*np.arange(self.n_pts_autocorr+1))
    tab_autocorrelation_symmetrized=np.concatenate((tab_autocorrelation,np.conj(tab_autocorrelation[:0:-1])))

# Make the inverse Fourier transform which is by construction real, so keep only real part
# Note that it is surely possible to improve using Hermitian FFT (useless as it uses very few resources)
# Both the spectrum and the energies are reordered in ascending order
    tab_spectrum=np.fft.fftshift(np.real(np.fft.ifft(tab_autocorrelation_symmetrized)))/self.e_resolution
#    tab_energies=np.fft.fftshift(np.fft.fftfreq(2*self.n_pts_autocorr+1,d=self.delta_t/(2.0*np.pi)))+e_middle
# The energy spectrum at this stage is starting at e=-n_pts_autocorr*delta_e and ending at e=-n_pts_autocorr*delta_e
# with delta_e = 2*pi/delta_t
    return tab_spectrum
"""
