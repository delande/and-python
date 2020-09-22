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
import anderson
import timeit

class Temporal_Propagation:
  def __init__(self, t_max, delta_t, method='che', accuracy=1.e-6, accurate_bounds=False, data_layout='real', want_cffi=True):
    self.t_max = t_max
    self.method = method
    self.want_cffi = want_cffi
    self.use_cffi = want_cffi
    self.data_layout = data_layout
    self.delta_t = delta_t
    self.script_delta_t = 0.
    self.accuracy = accuracy
    self.accurate_bounds = accurate_bounds
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

def apply_minus_i_h_gpe_complex(wfc, H, rhs):
  ntot=H.ntot
  if H.interaction == 0.0:
    rhs[0:2*ntot:2]=H.sparse_matrix.dot(wfc[1:2*ntot:2])
    rhs[1:2*ntot:2]=-H.sparse_matrix.dot(wfc[0:2*ntot:2])
# The next line makes everything in one call, but is significantly slower
#  rhs[:] = (-1j*H.sparse_matrix.dot(wfc.view(np.complex128))).view(np.float64)
  else:
    non_linear_phase = H.interaction*(wfc[0:2*ntot:2]**2+wfc[1:2*ntot:2]**2)
    rhs[0:2*ntot:2]=H.sparse_matrix.dot(wfc[1:2*ntot:2])+non_linear_phase*wfc[1:2*ntot:2]
    rhs[1:2*ntot:2]=-H.sparse_matrix.dot(wfc[0:2*ntot:2])-non_linear_phase*wfc[0:2*ntot:2]
#  print(wfc[200],wfc[201],rhs[200],rhs[201])
  return

def apply_minus_i_h_gpe_real(wfc, H, rhs):
#  print('wfc',wfc.dtype,wfc.shape)
  ntot=H.ntot
  if H.interaction == 0.0:
    rhs[0:ntot]=H.sparse_matrix.dot(wfc[ntot:2*ntot])
    rhs[ntot:2*ntot]=-H.sparse_matrix.dot(wfc[0:ntot])
  else:
    non_linear_phase = H.interaction*(wfc[0:ntot]**2+wfc[ntot:2*ntot]**2)
    rhs[0:ntot]=H.sparse_matrix.dot(wfc[ntot:2*ntot])+non_linear_phase*wfc[ntot:2*ntot]
    rhs[ntot:2*ntot]=-H.sparse_matrix.dot(wfc[0:ntot])-non_linear_phase*wfc[0:ntot]
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
# In low dimensions, one may use an optimized specific code
  use_sparse = False
  if H.dimension > 2:
    use_sparse = True
#  print(use_sparse)
  if use_sparse:
    psi_old[:] = c1*H.sparse_matrix.dot(psi[:])-c2*psi[:]+c_coef*wfc[:]-psi_old[:]
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


def chebyshev_step(wfc, H, propagation,timing,ffi,lib):
  if propagation.use_cffi:
    local_wfc = wfc.ravel()
    ntot = H.ntot
    max_order = propagation.tab_coef.size-1
    nonlinear_phase = ffi.new("double *", timing.MAX_NONLINEAR_PHASE)
    assert max_order%2==0,"Max order {} must be an even number".format(max_order)
    if propagation.data_layout=='real':
      psi_old = np.zeros(2*ntot)
      psi     = np.zeros(2*ntot)
      lib.chebyshev_real(H.dimension,ffi.from_buffer("int *",np.asarray(H.tab_dim,dtype=np.intc)),max_order,ffi.from_buffer("int *",H.array_boundary_condition),ffi.from_buffer("double *",wfc),ffi.from_buffer("double *",psi),ffi.from_buffer('double *',psi_old),ffi.from_buffer('double *',H.disorder),ffi.from_buffer('double *',propagation.tab_coef),ffi.from_buffer("double *",np.asarray(H.tab_tunneling)),H.two_over_delta_e,H.two_e0_over_delta_e,H.interaction*propagation.delta_t,H.medium_energy*propagation.delta_t,nonlinear_phase)
    else:
      psi_old = np.zeros(ntot,dtype=np.complex128)
      psi     = np.zeros(ntot,dtype=np.complex128)
      lib.chebyshev_complex(H.dimension,ffi.from_buffer("int *",np.asarray(H.tab_dim,dtype=np.intc)),max_order,ffi.from_buffer("int *",H.array_boundary_condition),ffi.from_buffer("double _Complex *",wfc),ffi.from_buffer("double _Complex *",psi),ffi.from_buffer('double _Complex *',psi_old),ffi.from_buffer('double *',H.disorder),ffi.from_buffer('double *',propagation.tab_coef),ffi.from_buffer("double *",np.asarray(H.tab_tunneling)),H.two_over_delta_e,H.two_e0_over_delta_e,H.interaction*propagation.delta_t,H.medium_energy*propagation.delta_t,nonlinear_phase)

    """
#      elementary_clenshaw_step_routine = lib.elementary_clenshaw_step_complex_1d
    psi = propagation.tab_coef[-1] * local_wfc
    lib.elementary_clenshaw_step_real_1d(dim_x,str.encode(boundary_condition),ffi.cast('double *',ffi.from_buffer(local_wfc)),ffi.cast('double *',ffi.from_buffer(psi)),ffi.cast('double *',ffi.from_buffer(psi_old)),propagation.tab_coef[-2], 2.0, 0,tunneling,ffi.cast('double *',ffi.from_buffer(H.disorder)),two_over_delta_e,two_e0_over_delta_e)
#    elementary_clenshaw_step_routine(local_wfc, H, psi, psi_old, propagation.tab_coef[-2], 2.0, 0)
    for order in range(propagation.tab_coef.size-3,0,-2):
 #     print(order,psi[0])
      lib.elementary_clenshaw_step_real_1d(dim_x,str.encode(boundary_condition),ffi.cast('double *',ffi.from_buffer(local_wfc)),ffi.cast('double *',ffi.from_buffer(psi_old)),ffi.cast('double *',ffi.from_buffer(psi)),propagation.tab_coef[order], 2.0, 1,tunneling,ffi.cast('double *',ffi.from_buffer(H.disorder)),two_over_delta_e,two_e0_over_delta_e)
      lib.elementary_clenshaw_step_real_1d(dim_x,str.encode(boundary_condition),ffi.cast('double *',ffi.from_buffer(local_wfc)),ffi.cast('double *',ffi.from_buffer(psi)),ffi.cast('double *',ffi.from_buffer(psi_old)),propagation.tab_coef[order-1], 2.0, 0,tunneling,ffi.cast('double *',ffi.from_buffer(H.disorder)),two_over_delta_e,two_e0_over_delta_e)
    lib.elementary_clenshaw_step_real_1d(dim_x,str.encode(boundary_condition),ffi.cast('double *',ffi.from_buffer(local_wfc)),ffi.cast('double *',ffi.from_buffer(psi_old)),ffi.cast('double *',ffi.from_buffer(psi)),propagation.tab_coef[0], 1.0, 1,tunneling,ffi.cast('double *',ffi.from_buffer(H.disorder)),two_over_delta_e,two_e0_over_delta_e)
 #   print('end_cffi',psi[0],psi[1],psi[dim_x-1])
    local_wfc[:]=psi[:]
 #   print('endend_cffi',local_wfc[0],local_wfc[1],local_wfc[dim_x-1],local_wfc[dim_x])
#      elementary_clenshaw_step_routine(dim_x,local_wfc, H, psi_old, psi, propagation.tab_coef[order], 2.0, 1)
#      elementary_clenshaw_step_routine(local_wfc, H, psi, psi_old, propagation.tab_coef[order-1], 2.0, 0)
#    elementary_clenshaw_step_routine(local_wfc, H, psi_old, psi, propagation.tab_coef[0], 1.0, 1)
    """
    return
  else:
    ntot = H.ntot
    max_order = propagation.tab_coef.size-1
    local_wfc = wfc.ravel()
    assert max_order%2==0,"Max order {} must be an even number".format(max_order)
    if propagation.data_layout == 'real':
      elementary_clenshaw_step_routine = elementary_clenshaw_step_real
      psi_old = np.zeros(2*ntot)
    else:
      elementary_clenshaw_step_routine = elementary_clenshaw_step_complex
      psi_old = np.zeros(ntot,dtype=np.complex128)
    psi = propagation.tab_coef[-1] * local_wfc
    c1 = 2.0*H.two_over_delta_e
    c2 = 2.0*H.two_e0_over_delta_e
    tab_c3 = 2.0*np.asarray(H.tab_tunneling)*H.two_over_delta_e
    elementary_clenshaw_step_routine(local_wfc,H,psi,psi_old,propagation.tab_coef[-2],False,c1,c2,tab_c3)
    for order in range(propagation.tab_coef.size-3,0,-2):
#      print(order,psi[0])
      elementary_clenshaw_step_routine(local_wfc,H,psi_old,psi,propagation.tab_coef[order],True,c1,c2,tab_c3)
      elementary_clenshaw_step_routine(local_wfc,H,psi,psi_old,propagation.tab_coef[order-1],False,c1,c2,tab_c3)
    c1 = H.two_over_delta_e
    c2 = H.two_e0_over_delta_e
    tab_c3 = np.asarray(H.tab_tunneling)*H.two_over_delta_e
    elementary_clenshaw_step_routine(local_wfc,H,psi_old,psi,propagation.tab_coef[0],True,c1,c2,tab_c3)

# old method inspired from old C code, slightly less efficient
    """
    method='old'
    if method=='old':
      if propagation.data_layout == 'real':
        elementary_clenshaw_step_routine = elementary_clenshaw_step_real_old
        psi_old = np.zeros(2*ntot)
      else:
        elementary_clenshaw_step_routine = elementary_clenshaw_step_complex_old
        psi_old = np.zeros(ntot,dtype=np.complex128)
      psi = propagation.tab_coef[-1] * local_wfc
      elementary_clenshaw_step_routine(local_wfc, H, psi, psi_old, propagation.tab_coef[-2], 2.0, 0)
      for order in range(propagation.tab_coef.size-3,0,-2):
#      print(order,psi[0])
        elementary_clenshaw_step_routine(local_wfc, H, psi_old, psi, propagation.tab_coef[order], 2.0, 1)
        elementary_clenshaw_step_routine(local_wfc, H, psi, psi_old, propagation.tab_coef[order-1], 2.0, 0)
      elementary_clenshaw_step_routine(local_wfc, H, psi_old, psi, propagation.tab_coef[0], 1.0, 1)
    else:
    """

#    print('end_no_cffi',psi[100],psi_old[100],wfc[100])
#    local_wfc[:]=psi[:]
  #  print(H.medium_energy)
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
      apply_minus_i_h_gpe_real(wfc, H, rhs)
#      print('inside gpe real',wfc[100],rhs[100])
    else:
#     print('inside gpe wfc',wfc.dtype,wfc.shape)
#     print('inside gpe rhs',rhs.dtype,rhs.shape)
      apply_minus_i_h_gpe_complex(wfc, H, rhs)
#      print('inside gpe complex',wfc[200],wfc[201],rhs[200],rhs[201])
    timing.GPE_TIME+=(timeit.default_timer() - start_time)
    timing.NUMBER_OF_OPS+=16.0*H.ntot
    return rhs

class Measurement:
  def __init__(self, delta_t_measurement, i_tab_0=0, measure_density=False, measure_density_momentum=False, measure_autocorrelation=False, measure_dispersion_position=False, measure_dispersion_position2=False, measure_dispersion_momentum=False, measure_dispersion_energy=False,measure_wavefunction=False, measure_wavefunction_momentum=False, measure_extended=False,use_mkl_fft=True):
    self.delta_t_measurement = delta_t_measurement
    self.i_tab_0 = i_tab_0
    self.measure_density = measure_density
    self.measure_density_momentum = measure_density_momentum
    self.measure_autocorrelation = measure_autocorrelation
    self.measure_dispersion_position = measure_dispersion_position
    self.measure_dispersion_position2 = measure_dispersion_position2
    self.measure_dispersion_momentum = measure_dispersion_momentum
    self.measure_dispersion_energy = measure_dispersion_energy
    self.measure_wavefunction = measure_wavefunction
    self.measure_wavefunction_momentum = measure_wavefunction_momentum
    self.extended = measure_extended
    self.use_mkl_fft = use_mkl_fft
    return

  def prepare_measurement(self,propagation,tab_delta,tab_dim):
    delta_t = propagation.delta_t
    t_max = propagation.t_max
    how_often_to_measure = int(self.delta_t_measurement/delta_t+0.5)
    propagation.delta_t = self.delta_t_measurement/how_often_to_measure
    number_of_measurements = int(t_max/self.delta_t_measurement+1.99999)
    number_of_time_steps = int(t_max/delta_t+0.99999)
    self.dimension = len(tab_dim)
    self.tab_i_measurement = np.arange(start=0,stop=number_of_measurements*how_often_to_measure,step=how_often_to_measure,dtype=int)
    self.tab_t_measurement = delta_t*self.tab_i_measurement
# correct the last time
    self.tab_i_measurement[number_of_measurements-1]=number_of_time_steps
    self.tab_t_measurement[number_of_measurements-1]=t_max
    dim_dispersion = [number_of_measurements]
    dim_dispersion_vec = [self.dimension,number_of_measurements]
    if self.measure_density:
      self.density_final = np.zeros(tab_dim)
#      print(self.density_final.shape,tab_dim)
    if self.measure_autocorrelation:
      self.tab_autocorrelation = np.zeros(number_of_measurements,dtype=np.complex128)
    if self.measure_density_momentum:
      self.density_momentum_final = np.zeros(tab_dim)
    if self.measure_density_momentum or self.measure_dispersion_momentum or self.measure_wavefunction_momentum:
      self.frequencies = []
      for i in range(self.dimension):
        self.frequencies.append(np.fft.fftshift(np.fft.fftfreq(tab_dim[i],d=tab_delta[i]/(2.0*np.pi))))
    if self.measure_dispersion_position:
      self.tab_position = np.zeros(dim_dispersion_vec)
    if self.measure_dispersion_position2:
      self.tab_position2 = np.zeros(dim_dispersion_vec)
    if self.measure_dispersion_momentum:
      self.tab_momentum = np.zeros(dim_dispersion_vec)
    if self.measure_dispersion_energy:
      self.tab_energy = np.zeros(dim_dispersion)
      self.tab_nonlinear_energy = np.zeros(dim_dispersion)
    if self.measure_wavefunction:
      self.wfc =  np.zeros(tab_dim,dtype=np.complex128)
    if self.measure_wavefunction_momentum:
      self.wfc_momentum =  np.zeros(tab_dim,dtype=np.complex128)
    return

  def prepare_measurement_global(self,propagation,tab_delta,tab_dim):
    delta_t = propagation.delta_t
    t_max = propagation.t_max
    how_often_to_measure = int(self.delta_t_measurement/delta_t+0.5)
    propagation.delta_t = self.delta_t_measurement/how_often_to_measure
    number_of_measurements = int(t_max/self.delta_t_measurement+1.99999)
    number_of_time_steps = int(t_max/delta_t+0.99999)
    self.dimension = len(tab_dim)
    self.tab_i_measurement = np.arange(start=0,stop=number_of_measurements*how_often_to_measure,step=how_often_to_measure,dtype=int)
    self.tab_t_measurement = delta_t*self.tab_i_measurement
# correct the last time
    self.tab_i_measurement[number_of_measurements-1]=number_of_time_steps
    self.tab_t_measurement[number_of_measurements-1]=t_max
    dim_density = tab_dim[:]
    dim_dispersion = [number_of_measurements]
    dim_dispersion_vec = [self.dimension,number_of_measurements]
    if self.extended:
      dim_density.insert(0,2)
      dim_dispersion.insert(0,2)
      dim_dispersion_vec.insert(0,2)
    else:
      dim_density.insert(0,1)
      dim_dispersion.insert(0,1)
      dim_dispersion_vec.insert(0,1)
#    print(dim_density)
#    print(dim_dispersion)
#    print(dim_dispersion_vec)
    if self.measure_density:
      self.density_final = np.zeros(dim_density)
    if self.measure_autocorrelation:
      self.tab_autocorrelation = np.zeros(number_of_measurements,dtype=np.complex128)
    if self.measure_density_momentum:
      self.density_momentum_final = np.zeros(dim_density)
    if self.measure_density_momentum or self.measure_dispersion_momentum or self.measure_wavefunction_momentum:
      self.frequencies = []
      for i in range(self.dimension):
        self.frequencies.append(np.fft.fftshift(np.fft.fftfreq(tab_dim[i],d=tab_delta[i]/(2.0*np.pi))))
    if self.measure_dispersion_position:
      self.tab_position = np.zeros(dim_dispersion_vec)
    if self.measure_dispersion_position2:
      self.tab_position2 = np.zeros(dim_dispersion_vec)
    if self.measure_dispersion_momentum:
        self.tab_momentum = np.zeros(dim_dispersion_vec)
    if self.measure_dispersion_energy:
      self.tab_energy = np.zeros(dim_dispersion)
      self.tab_nonlinear_energy = np.zeros(dim_dispersion)
    if self.measure_wavefunction:
      self.wfc =  np.zeros(tab_dim,dtype=np.complex128)
    if self.measure_wavefunction_momentum:
      self.wfc_momentum =  np.zeros(tab_dim,dtype=np.complex128)
    return

  def merge_measurement(self,measurement):
    if self.measure_density:
#      print(measurement.density_final.shape)
#      print(self.density_final.shape)
      self.density_final[0] += measurement.density_final
      if self.extended:
        self.density_final[1] += measurement.density_final**2
    if self.measure_density_momentum:
      self.density_momentum_final[0] += measurement.density_momentum_final
      if self.extended:
        self.density_momentum_final[1] += measurement.density_momentum_final**2
    if self.measure_autocorrelation:
      self.tab_autocorrelation += measurement.tab_autocorrelation
    if self.measure_dispersion_position:
      self.tab_position[0] += measurement.tab_position
      if self.extended:
        self.tab_position[1] += measurement.tab_position**2
    if self.measure_dispersion_position2:
      self.tab_position2[0] += measurement.tab_position2
      if self.extended:
        self.tab_position2[1] += measurement.tab_position2**2
    if self.measure_dispersion_momentum:
      self.tab_momentum[0] += measurement.tab_momentum
      if self.extended:
        self.tab_momentum[1] += measurement.tab_momentum**2
    if self.measure_dispersion_energy:
      self.tab_energy[0] += measurement.tab_energy
      self.tab_nonlinear_energy[0] += measurement.tab_nonlinear_energy
      if self.extended:
        self.tab_energy[1] += measurement.tab_energy**2
        self.tab_nonlinear_energy[1] += measurement.tab_nonlinear_energy**2
    if self.measure_wavefunction:
      self.wfc += measurement.wfc
    if self.measure_wavefunction_momentum:
      self.wfc_momentum += measurement.wfc_momentum
    return

  def mpi_merge_measurement(self,comm,timing):
    start_mpi_time = timeit.default_timer()
    try:
      from mpi4py import MPI
    except ImportError:
      print("mpi4py is not found!")
      return
    if self.measure_density:
      toto = np.empty_like(self.density_final)
      comm.Reduce(self.density_final,toto)
      self.density_final = np.copy(toto)
    if self.measure_density_momentum:
      toto = np.empty_like(self.density_momentum_final)
      comm.Reduce(self.density_momentum_final,toto)
      self.density_momentum_final = np.copy(toto)
    if self.measure_autocorrelation:
      toto = np.empty_like(self.tab_autocorrelation)
      comm.Reduce(self.tab_autocorrelation,toto)
      self.tab_autocorrelation = np.copy(toto)
    if self.measure_dispersion_position:
      toto = np.empty_like(self.tab_position)
      comm.Reduce(self.tab_position,toto)
      self.tab_position = np.copy(toto)
    if self.measure_dispersion_position2:
      toto = np.empty_like(self.tab_position2)
      comm.Reduce(self.tab_position2,toto)
      self.tab_position2 =  np.copy(toto)
    if self.measure_dispersion_momentum:
      toto = np.empty_like(self.tab_momentum)
      comm.Reduce(self.tab_momentum,toto)
      self.tab_momentum = np.copy(toto)
    if self.measure_dispersion_energy:
      toto = np.empty_like(self.tab_energy)
      comm.Reduce(self.tab_energy,toto)
      self.tab_energy =  np.copy(toto)
      comm.Reduce(self.tab_nonlinear_energy,toto)
      self.tab_nonlinear_energy = np.copy(toto)
    if self.measure_wavefunction:
      toto = np.empty_like(self.wfc)
      comm.Reduce(self.wfc,toto)
      self.wfc = np.copy(toto)
    if self.measure_wavefunction_momentum:
      toto = np.empty_like(self.wfc_momentum)
      comm.Reduce(self.wfc_momentum,toto)
      self.wfc_momentum = np.copy(toto)
    timing.MPI_TIME+=(timeit.default_timer() - start_mpi_time)
    return

  def normalize(self,n_config):
    if self.measure_density:
      self.density_final /= n_config
      if self.extended:
        self.density_final[1] = np.sqrt(np.abs(self.density_final[1]-self.density_final[0]**2)/n_config)
    if self.measure_density_momentum:
      self.density_momentum_final /= n_config
      if self.extended:
        self.density_momentum_final[1] = np.sqrt(np.abs(self.density_momentum_final[1]-self.density_momentum_final[0]**2)/n_config)
    if self.measure_autocorrelation:
      self.tab_autocorrelation /= n_config
    list_of_columns = [self.tab_t_measurement]
    tab_strings=['Column 1: Time']
    next_column = 2
    if self.measure_dispersion_position:
      self.tab_position /= n_config
      if self.tab_position.shape[0]==2:
        self.tab_position[1] = np.sqrt(np.abs(self.tab_position[1]-self.tab_position[0]**2)/n_config)
    if self.measure_dispersion_position2:
      self.tab_position2 /= n_config
      if self.tab_position2.shape[0]==2:
        self.tab_position2[1] = np.sqrt(np.abs(self.tab_position2[1]-self.tab_position2[0]**2)/n_config)
    if self.measure_dispersion_position or self.measure_dispersion_position2:
      for i in range(self.dimension):
        if self.measure_dispersion_position:
          list_of_columns.append(self.tab_position[0,i])
          tab_strings.append('Column '+str(next_column)+': <r_'+str(i+1)+'>')
          next_column += 1
          if self.tab_position.shape[0]==2:
            list_of_columns.append(self.tab_position[1,i])
            tab_strings.append('Column '+str(next_column)+': Standard deviation of <r_'+str(i+1)+'>')
            next_column += 1
        if self.measure_dispersion_position2:
          list_of_columns.append(self.tab_position2[0,i])
          tab_strings.append('Column '+str(next_column)+': <r_'+str(i+1)+'^2>')
          next_column += 1
          if self.tab_position2.shape[0]==2:
            list_of_columns.append(self.tab_position2[1,i])
            tab_strings.append('Column '+str(next_column)+': Standard deviation of <r_'+str(i+1)+'^2>')
            next_column += 1
    if self.measure_dispersion_momentum:
      self.tab_momentum /= n_config
      if self.tab_momentum.shape[0]==2:
        self.tab_momentum[1] = np.sqrt(np.abs(self.tab_momentum[1]-self.tab_momentum[0]**2)/n_config)
      for i in range(self.dimension):
        list_of_columns.append(self.tab_momentum[0,i])
        tab_strings.append('Column '+str(next_column)+': <p_'+str(i+1)+'>')
        next_column += 1
        if self.tab_momentum.shape[0]==2:
          list_of_columns.append(self.tab_momentum[1,i])
          tab_strings.append('Column '+str(next_column)+': Standard deviation of <p_'+str(i+1)+'>')
          next_column += 1
    if self.measure_dispersion_energy:
      self.tab_energy /= n_config
      self.tab_nonlinear_energy /= n_config
      list_of_columns.append(self.tab_energy[0])
      tab_strings.append('Column '+str(next_column)+': Total energy')
      next_column += 1
      if self.tab_energy.shape[0]==2:
        self.tab_energy[1] = np.sqrt(np.abs(self.tab_energy[1]-self.tab_energy[0]**2)/n_config)
        list_of_columns.append(self.tab_energy[1])
        tab_strings.append('Column '+str(next_column)+': Standard deviation of total energy')
        next_column += 1
      list_of_columns.append(self.tab_nonlinear_energy[0])
      tab_strings.append('Column '+str(next_column)+': Nonlinear energy')
      next_column += 1
      if self.tab_nonlinear_energy.shape[0]==2:
        self.tab_nonlinear_energy[1] = np.sqrt(np.abs(self.tab_nonlinear_energy[1]-self.tab_nonlinear_energy[0]**2)/n_config)
        list_of_columns.append(self.tab_nonlinear_energy[1])
        tab_strings.append('Column '+str(next_column)+': Standard deviation of nonlinear energy')
        next_column += 1
    if self.measure_wavefunction:
      self.wfc /= n_config
    if self.measure_wavefunction_momentum:
      self.wfc_momentum /= n_config
#    print(tab_strings)
#    print(list_of_columns)

    return tab_strings, np.column_stack(list_of_columns)

  def perform_measurement(self, i_tab, H, psi, init_state_autocorr):
    if self.measure_dispersion_position or self.measure_dispersion_position2:
      density = psi.wfc.real**2+psi.wfc.imag**2
      norm = np.sum(density)
      for i in range(psi.dimension):
        local_density = np.sum(density, axis = tuple(j for j in range(psi.dimension) if j!=i))
#    print(dim,local_density.shape,local_density)
        if self.measure_dispersion_position:
          self.tab_position[i,i_tab] = np.sum(psi.tab_position[i]*local_density)/norm
        if self.measure_dispersion_position2:
          self.tab_position2[i,i_tab] = np.sum(psi.tab_position[i]**2*local_density)/norm
    if self.measure_dispersion_energy:
      self.tab_energy[i_tab], self.tab_nonlinear_energy[i_tab] = psi.energy(H)
    if (self.measure_dispersion_momentum):
      psi_momentum = psi.convert_to_momentum_space(self.use_mkl_fft)
      density = psi_momentum.real**2+psi_momentum.imag**2
      norm = np.sum(density)
      for i in range(psi.dimension):
        local_density = np.sum(density, axis = tuple(j for j in range(psi.dimension) if j!=i))
        self.tab_momentum[i,i_tab] = np.sum(self.frequencies[i]*local_density)/norm
    if self.measure_autocorrelation and i_tab>=self.i_tab_0:
# Inlining the overlap method is slighlty faster
#          measurement.tab_autocorrelation[i_tab-i_tab_0] = psi.overlap(init_state_autocorr)
      self.tab_autocorrelation[i_tab-self.i_tab_0] = np.vdot(init_state_autocorr.wfc,psi.wfc)*H.delta_vol
    if i_tab==self.tab_i_measurement.size-1:
# This is the last measurement
# compute some needed quantities
      if self.measure_density:
        self.density_final = psi.wfc.real**2+psi.wfc.imag**2
      if self.measure_wavefunction:
        self.wfc = psi.wfc
      if self.measure_wavefunction_momentum:
        if self.measure_dispersion_momentum:
# Wavefunction in momentum space has already been computed
          self.wfc_momentum = psi_momentum
        else:
          self.wfc_momentum = psi.convert_to_momentum_space(self.use_mkl_fft)
      if self.measure_density_momentum:
        if self.measure_dispersion_momentum:
# Density in momentum space has already been computed
          self.density_momentum_final = density
        else:
          if self.measure_wavefunction_momentum:
            self.density_momentum_final = self.wfc_momentum.real**2+self.wfc_momentum.imag**2
          else:
            psi_momentum = psi.convert_to_momentum_space(self.use_mkl_fft)
            self.density_momentum_final = psi_momentum.real**2+psi_momentum.imag**2
      return



class Spectral_function:
  def __init__(self,e_range,e_resolution):
    self.n_pts_autocorr = int(0.5*e_range/e_resolution+0.5)
# In case e_range/e_resolution is not an integer, I keep e_resolution and rescale e_range
    self.e_range = 2.0*e_resolution*self.n_pts_autocorr
    self.delta_t = 2.0*np.pi/(self.e_range*(1.0+0.5/self.n_pts_autocorr))
    self.t_max = self.delta_t*self.n_pts_autocorr
    self.e_resolution = e_resolution
    return

  def compute_spectral_function(self,tab_autocorrelation):
# The autocorrelation function for negative time is simply the complex conjugate of the one at positive time
# We will use an inverse FFT, so that positive time must be first, followed by negative times (all increasing)
# see manual of numpy.fft.ifft for explanations
# The number of points in tab_autocorrelation is n_pts_autocorr+1
    tab_autocorrelation_symmetrized=np.concatenate((tab_autocorrelation,np.conj(tab_autocorrelation[:0:-1])))
# Make the inverse Fourier transform which is by construction real, so keep only real part
# Note that it is surely possible to improve using Hermitian FFT (useless as it uses very few resources)
# Both the spectrum and the energies are reordered in ascending order
    tab_spectrum=np.fft.fftshift(np.real(np.fft.ifft(tab_autocorrelation_symmetrized)))/self.e_resolution
    tab_energies=np.fft.fftshift(np.fft.fftfreq(2*self.n_pts_autocorr+1,d=self.delta_t/(2.0*np.pi)))
    return tab_energies,tab_spectrum


def gpe_evolution(i_seed, initial_state, H, propagation, measurement, timing, debug=False):
  assert propagation.data_layout in ["real","complex"]
#  assert H.boundary_condition in ["periodic","open"]
  assert propagation.method in ["ode","che"]
  def solout(t,y):
    timing.N_SOLOUT+=1
    return None

  start_dummy_time=timeit.default_timer()
#  dimension = H.dimension
  tab_dim = H.tab_dim
  tab_delta = H.tab_delta
  ntot = H.ntot
  psi = anderson.Wavefunction(tab_dim,tab_delta)

#  print('start gen disorder',timeit.default_timer())
  H.generate_disorder(seed=i_seed+1234)
#  timing.DUMMY_TIME+=(timeit.default_timer() - start_dummy_time)
  if H.dimension>2 or (propagation.accurate_bounds and propagation.method=='che'):
    H.generate_sparse_matrix()

#  timing.DUMMY_TIME+=(timeit.default_timer() - start_dummy_time)
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
    rhs = np.zeros(2*ntot)
#    print('y',y.dtype,y.shape)
#    print('rhs',rhs.dtype,rhs.shape)
    solver = ode(f=lambda t,y: gross_pitaevskii(t,y,H,propagation.data_layout,rhs,timing)).set_integrator('dop853', atol=1e-5, rtol=1e-4)
    solver.set_solout(solout)
    solver.set_initial_value(y)
  if propagation.method=='che':
    H.energy_range(accurate=propagation.accurate_bounds)
##    H.medium_energy = 0.5*(e_min+e_max)
#    print(H.e_min,H.e_max)
    #H.script_tunneling, H.script_disorder =
#    H.script_h(e_min,e_max)
    propagation.script_delta_t = 0.5*propagation.delta_t*(H.e_max-H.e_min)
    accuracy = propagation.accuracy
    propagation.compute_chebyshev_coefficients(accuracy,timing)
    if propagation.want_cffi:
#      print('I want CFFI')
      try:
        from anderson._chebyshev import ffi,lib
        if propagation.data_layout == 'real':
#        print('chebyshev_clenshaw_real_'+str(H.dimension)+'d')
          propagation.use_cffi =  hasattr(lib,'chebyshev_real') and hasattr(lib,'elementary_clenshaw_step_real_'+str(H.dimension)+'d')
        if propagation.data_layout == 'complex':
#          print(hasattr(lib,'chebyshev_complex'))
#          print(hasattr(lib,'elementary_clenshaw_step_complex_real_coef_'+str(H.dimension)+'d'))
          propagation.use_cffi =  hasattr(lib,'chebyshev_complex') and hasattr(lib,'elementary_clenshaw_step_complex_'+str(H.dimension)+'d')
      except ImportError:
#        print('Could not import ffi')
        propagation.use_cffi = False
        ffi = None
        lib = None
      if not propagation.use_cffi and H.seed == 1234:
        print("\nWarning, no C version found, this uses the slow Python version!\n")
    else:
      propagation.use_cffi = False
      ffi = None
      lib = None

#  timing.DUMMY_TIME+=(timeit.default_timer() - start_dummy_time)

#  print('1',initial_state.wfc[0],initial_state.wfc[1])


#  print(timeit.default_timer())
  timing.DUMMY_TIME+=(timeit.default_timer() - start_dummy_time)

  start_expect_time = timeit.default_timer()
  if measurement.measure_autocorrelation:
# Create a full structure for init_state_autocorr (the initial state for autocorrelation) and copy initial_state in it if i_tab_0=0
    init_state_autocorr = anderson.Wavefunction(tab_dim,tab_delta)
    if (measurement.i_tab_0==0):
      init_state_autocorr.wfc[:] = initial_state.wfc[:]
  else:
# If no autocorrelation, init_state_autocorr will not be used, it can refer to anything
    init_state_autocorr = initial_state
  measurement.perform_measurement(0, H, initial_state, initial_state)
  timing.EXPECT_TIME+=(timeit.default_timer() - start_expect_time)
#  print('2',initial_state.wfc[0],initial_state.wfc[1])

#  print(measurement.tab_i_measurement)
#time evolution
  i_tab = 1
  for i_prop in range(1,measurement.tab_i_measurement[-1]+1):
    t_next=min(i_prop*propagation.delta_t,propagation.t_max)
#     print(i_prop,t_next)
    if (propagation.method == 'ode'):
      start_ode_time = timeit.default_timer()
      solver.integrate(t_next)
      timing.ODE_TIME+=(timeit.default_timer() - start_ode_time)
    else:
      start_che_time = timeit.default_timer()
#      print(i_prop,start_che_time)
#      print(timing.MAX_NONLINEAR_PHASE)
      chebyshev_step(y, H, propagation,timing,ffi,lib)
#      print(np.vdot(y,y)*H.delta_vol)
#      print(timing.MAX_NONLINEAR_PHASE)
#      print(y[2000])
      timing.CHE_TIME+=(timeit.default_timer() - start_che_time)
      timing.NUMBER_OF_OPS+=(12.0+6.0*H.dimension)*ntot*propagation.tab_coef.size
    if i_prop==measurement.tab_i_measurement[i_tab]:
      start_dummy_time=timeit.default_timer()
      if (propagation.method == 'ode'): y=solver.y
#      print('3',psi.wfc.shape,psi.wfc.dtype,y.shape,y.dtype)
      if propagation.data_layout=='real':
# The following two lines are faster than the natural implementation psi.wfc= y[0:dim_x]+1j*y[dim_x:2*dim_x]
        psi.wfc.real=y[0:ntot].reshape(tab_dim)
        psi.wfc.imag=y[ntot:2*ntot].reshape(tab_dim)
      else:
#        print( y.view(np.complex128).shape)
        psi.wfc[:] = y.view(np.complex128).reshape(tab_dim)[:]
#      print('4',psi.wfc.shape,psi.wfc.dtype)
      timing.DUMMY_TIME+=(timeit.default_timer() - start_dummy_time)
      start_expect_time = timeit.default_timer()
#      print(start_expect_time)
      if (i_tab==measurement.i_tab_0):
        init_state_autocorr.wfc[:] = psi.wfc[:]
      measurement.perform_measurement(i_tab, H, psi, init_state_autocorr)
      timing.EXPECT_TIME+=(timeit.default_timer() - start_expect_time)
      i_tab+=1
#    print('3',initial_state.wfc[0],initial_state.wfc[1])
  return


"""
 def output_string(self, H, propagation,initial_state,n_config):
#    environment_string='Script '+os.path.basename(__file__)+' ran by '+getpass.getuser()+' on machine '+os.uname()[1]+'\n'\
#                      +datetime.datetime.now().strftime("%Y-%m-%d %H:%M")+'\n'
    params_string='Disorder type                   = '+H.disorder_type+'\n'\
                 +'Lx                              = '+str(H.dim_x*H.delta_x)+'\n'\
                 +'dx                              = '+str(H.delta_x)+'\n'\
                 +'Nx                              = '+str(H.dim_x)+'\n'\
                 +'V0                              = '+str(H.disorder_strength)+'\n'\
                 +'g                               = '+str(H.interaction)+'\n'\
                 +'Boundary Condition              = '+H.boundary_condition+'\n'\
                 +'Initial state                   = '+initial_state.type+'\n'\
                 +'k_0                             = '+str(initial_state.k_0)+'\n'\
                 +'sigma_0                         = '+str(initial_state.sigma_0)+'\n'\
                 +'Integration Method              = '+str(propagation.method)+'\n'\
                 +'time step                       = '+str(propagation.delta_t)+'\n'\
                 +'time step for measurement       = '+str(self.delta_t_measurement)+'\n'\
                 +'total time                      = '+str(propagation.t_max)+'\n'\
                 +'Number of disorder realizations = '+str(n_config)+'\n'\
                 +'\n'
#    print(params_string)
#                 +'first measurement step          = '+str(first_measurement_autocorr)+'\n'\
#                  +'total measurement time          = '+str(t_max-first_measurement_autocorr*delta_t_measurement)+'\n'\

  return params_string
"""


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
"""

"""
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
"""

