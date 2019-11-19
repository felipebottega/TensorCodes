"""
 Gauss-Newton Module
 ===================
 This module implement the damped Gauss-Newton algorithm, with iterations performed with aid of the conjugate gradient 
 method.

 References
 ==========

 - K. Madsen, H. B. Nielsen, and O. Tingleff, Methods for Non-Linear Least Squares Problems, 2nd edition,
   Informatics and Mathematical Modelling, Technical University of Denmark, 2004.
"""

# Python modules
import numpy as np
from numpy import inf, mean, copy, concatenate, empty, array, zeros, ones, float64, sqrt, dot, linspace, nan
from numpy.linalg import norm
from numpy.random import randint
import sys
from numba import njit

# Tensor Fox modules
import Alternating_Least_Squares as als
import Conversion as cnv
import Critical as crt
import MultilinearAlgebra as mlinalg


def dGN(T, factors, R, init_error, options):
    """
    This function uses the Damped Gauss-Newton method to compute an approximation of T with rank R. A starting point to
    initiate the iterations must be given. This point is given by the parameter factors.
    The Damped Gauss-Newton method is an iterative method, updating a point x at each iteration. The last computed x is
    gives an approximate CPD in flat form, and from this we have the components to form the actual CPD.

    Inputs
    ------
    T: float array
    factors: list of 2-D arrays
        The factor matrices used as starting point.
    R: int
        The desired rank of the approximating tensor.
    init_error: float
        Relative error of the initial approximation.
    options: class
        Class with the options. See the Auxiliar module documentation for more information.

    Outputs
    -------
    best_factors: list of 2-D arrays
        The factor matrices of the approximated CPD of T.
    step_sizes: float 1-D array
        Distance between the computed points at each iteration.
    errors: float 1-D array
        Error of the computed approximating tensor at each iteration. 
    improv: float 1-D array
        Improvement of the error at each iteration. More precisely, the difference between the relative error of the
        current iteration and the previous one.
    gradients: float 1-D array
        Gradient of the error function at each iteration.
    stop: 0, 1, 2, 3, 4, 5 or 6
        This value indicates why the dGN function stopped. Below we summarize the cases.
        0: errors[it] < tol. Relative error is small enough.
        1: step_sizes[it] < tol_steps. Steps are small enough.
        2: improv[it] < tol_improv. Improvement in the relative error is small enough.
        3: gradients[it] < tol_grad. Gradient is small enough (infinity norm).
        4: mean(abs(errors[it-k : it] - errors[it-k-1 : it-1]))/Tsize < 10*tol_improv. Average of the last
            k = 1 + int(maxiter/10) relative errors is small enough. Keeping track of the averages is useful when the
            errors improvements are just a little above the threshold for a long time. We want them above the threshold
            indeed, but not too close for a long time.
        5: limit of iterations reached.
        6: dGN diverged.
        7: no refinement was performed (this is not really a stopping condition, but it is necessary to indicate when
        the program can't give a stopping condition in the refinement stage).
    """

    # INITIALIZE RELEVANT VARIABLES 

    # Extract all variable from the class of options.
    init_damp = options.init_damp
    maxiter = options.maxiter
    tol = options.tol
    tol_step = options.tol_step
    tol_improv = options.tol_improv
    tol_grad = options.tol_grad
    symm = options.symm
    display = options.display
    low, upp, factor = options.constraints
    factors_norm = options.factors_norm
    inner_method, cg_maxiter, cg_factor, cg_tol = [options.inner_method,
                                                   options.cg_maxiter,
                                                   options.cg_factor,
                                                   options.cg_tol]

    # Verify if some factor should be fixed or not. This only happens when the bicpd function was called.
    L = len(factors)
    fix_mode = -1
    orig_factors = [[] for l in range(L)]
    for l in range(L):
        if type(factors[l]) == list:
            fix_mode = l
            orig_factors[l] = factors[l][0].copy()
            factors[l] = factors[l][0]

    # Set the other variables.
    dims = T.shape
    Tsize = norm(T)
    error = 1
    best_error = init_error
    stop = 5
    if type(init_damp) == list:
        damp = init_damp[0]
    else:
        damp = init_damp * mean(np.abs(T))
    const = 1 + int(maxiter / 10)

    # INITIALIZE RELEVANT ARRAYS

    x = concatenate([factors[l].flatten('F') for l in range(L)])
    y = zeros(R * sum(dims), dtype=float64)
    step_sizes = empty(maxiter)
    errors = empty(maxiter)
    improv = empty(maxiter)
    gradients = empty(maxiter)
    best_factors = [copy(factors[l]) for l in range(L)]

    # Prepare data to use in each Gauss-Newton iteration.
    data = prepare_data(dims, R)

    # Compute unfoldings.
    Tl = [cnv.unfold(T, l+1) for l in range(L)]
    T1_approx = empty(Tl[0].shape, dtype=float64)

    if display > 1:
        if display == 4:
            print('   ',
                  '{:^9}'.format('Iteration'),
                  '| {:^11}'.format('Rel error'),
                  '| {:^11}'.format('Step size'),
                  '| {:^11}'.format('Improvement'),
                  '| {:^11}'.format('norm(grad)'),
                  '| {:^11}'.format('Predicted error'),
                  '| {:^10}'.format('# Inner iterations'))
        else:
            print('   ',
                  '{:^9}'.format('Iteration'),
                  '| {:^9}'.format('Rel error'),
                  '| {:^11}'.format('Step size'),
                  '| {:^10}'.format('Improvement'),
                  '| {:^10}'.format('norm(grad)'),
                  '| {:^10}'.format('Predicted error'),
                  '| {:^10}'.format('# Inner iterations'))

            # START GAUSS-NEWTON ITERATIONS

    for it in range(maxiter):
        # Keep the previous value of x and error to compare with the new ones in the next iteration.
        old_x = x
        old_error = error

        # Computation of the Gauss-Newton iteration formula to obtain the new point x + y, where x is the 
        # previous point and y is the new step obtained as the solution of min_y |Ay - b|, with 
        inner_parameters = \
            damp, inner_method, cg_maxiter, cg_factor, cg_tol, low, upp, factor, symm, factors_norm, fix_mode
        T1_approx, factors, x, y, grad, itn, residualnorm, error = compute_step(Tsize, Tl, T1_approx, factors,
                                                                                orig_factors, data, x, y,
                                                                                inner_parameters, it)
        # Update best solution.
        if error < best_error:
            best_error = error
            for l in range(L):
                best_factors[l] = copy(factors[l])

        # Update damp. 
        damp = update_damp(damp, init_damp, old_error, error, residualnorm, it)

        # Save relevant information about the current iteration.
        errors[it] = error
        step_sizes[it] = norm(x - old_x) / norm(old_x)
        gradients[it] = norm(grad, inf)
        if it == 0:
            improv[it] = errors[it]
        else:
            improv[it] = np.abs(errors[it - 1] - errors[it])

        # Show information about current iteration.
        if display > 1:
            if display == 4:
                print('    ',
                      '{:^8}'.format(it + 1),
                      '| {:^10.5e}'.format(errors[it]),
                      '| {:^10.5e}'.format(step_sizes[it]),
                      '| {:^10.5e}'.format(improv[it]),
                      '| {:^11.5e}'.format(gradients[it]),
                      '| {:^15.5e}'.format(residualnorm),
                      '| {:^16}'.format(itn))
            else:
                print('   ',
                      '{:^9}'.format(it + 1),
                      '| {:^9.2e}'.format(errors[it]),
                      '| {:^11.2e}'.format(step_sizes[it]),
                      '| {:^11.2e}'.format(improv[it]),
                      '| {:^10.2e}'.format(gradients[it]),
                      '| {:^15.2e}'.format(residualnorm),
                      '| {:^16}'.format(itn))

        # Stopping conditions.
        if it > 1:
            if errors[it] < tol:
                stop = 0
                break
            if step_sizes[it] < tol_step:
                stop = 1
                break
            if improv[it] < tol_improv:
                stop = 2
                break
            if gradients[it] < tol_grad:
                stop = 3
                break
            # Let const=1+int(maxiter/10). Comparing the average errors of const consecutive iterations prevents the
            # program to continue iterating when the error starts to oscillate.
            if it > 2*const and it % const == 0:
                mean1 = mean(errors[it - 2*const: it - const])
                mean2 = mean(errors[it - const: it])
                if mean1 - mean2 <= tol_improv:
                    stop = 4
                    break
            # Prevent blow ups.
            if error > max(1, Tsize ** 2) / (1e-16 + tol):
                stop = 6
                break

                # SAVE LAST COMPUTED INFORMATION

    errors = errors[0: it+1]
    step_sizes = step_sizes[0: it+1]
    improv = improv[0: it+1]
    gradients = gradients[0: it+1]

    return best_factors, step_sizes, errors, improv, gradients, stop


def compute_step(Tsize, Tl, T1_approx, factors, orig_factors, data, x, y, inner_parameters, it):
    """    
    This function uses the chosen inner method to compute the next step.
    """

    # Initialize first variables.
    L = len(factors)
    damp, inner_method, cg_maxiter, cg_factor, cg_tol, low, upp, factor, symm, factors_norm, fix_mode = inner_parameters
    if type(inner_method) == list:
        inner_method = inner_method[it]

    # Call the inner method.
    if inner_method == 'cg' or inner_method == 'cg_static':
        if inner_method == 'cg':
            cg_maxiter = 1 + int(cg_factor * randint(1 + it ** 0.4, 2 + it ** 0.9))
        y, grad, Gr, itn, residualnorm = cg(Tl, factors, data, y, damp, cg_maxiter, cg_tol)

    elif inner_method == 'als':
        factors = als.als_iteration(Tl, factors, fix_mode)
        x = concatenate([factors[l].flatten('F') for l in range(L)])
        y *= 0

    else:
        sys.exit("Wrong inner method name. Must be 'cg', 'cg_static' or 'als'.")

    # Update results.
    x = x + y

    # Balance and transform factors.
    factors = cnv.x2cpd(x, Gr, factors)
    factors = cnv.transform(factors, low, upp, factor, symm, factors_norm)
    # Some mode may be fixed when the bicpd is called.
    if L == 3:
        for l in range(L):
            if fix_mode == l:
                factors[l] = copy(orig_factors[l])

    # Compute error.
    T1_approx = cnv.cpd2unfold1(T1_approx, factors)
    error = crt.fastnorm(Tl[0], T1_approx) / Tsize

    if inner_method == 'als':
        return T1_approx, factors, x, y, [nan], '-', Tsize*error, error

    return T1_approx, factors, x, y, grad, itn, residualnorm, error


def cg(Tl, factors, data, y, damp, maxiter, tol):
    """
    Conjugate gradient algorithm specialized to the tensor case.
    """

    L = len(factors)
    R = factors[0].shape[1]
    dims = [factors[l].shape[0] for l in range(L)]
    maxiter = min(maxiter, R * sum(dims))

    # Give names to the arrays.
    Gr, P1, P2, A, B, P_VT_W, tmp, result, Gamma, gamma, sum_dims, M, residual_cg, P, Q, z, g = data

    # Compute the values of all arrays.
    Gr, P1, P2 = gramians(factors, Gr, P1, P2)
    Gamma, gamma = regularization(factors, Gamma, gamma, P1, dims, sum_dims)
    M = precond(Gamma, gamma, M, damp, dims, sum_dims)
    
    y *= 0

    # CG iterations.
    grad = -compute_grad(Tl, factors, P1, g, dims, sum_dims)
    residual_cg = M * grad
    P = residual_cg
    residualnorm = dot(residual_cg.T, residual_cg)
    if residualnorm == 0.0:
        residualnorm = 1e-6
    y, itn, residualnorm = cg_iterations(factors, P1, P2, A, B, P_VT_W, tmp, result,
                                         M, P, Gamma, damp, z, residual_cg, residualnorm, y, tol, maxiter, dims, sum_dims)
    return M * y, grad, Gr, itn + 1, residualnorm


def cg_iterations(factors, P1, P2, A, B, P_VT_W, tmp, result,
                  M, P, Gamma, damp, z, residual_cg, residualnorm, y, tol, maxiter, dims, sum_dims):
    """
    Conjugate gradient iterations.
    """

    L = len(dims)
    R = factors[0].shape[1]

    for itn in range(maxiter):
        Q = M * P
        V = [ Q[sum_dims[l]: sum_dims[l+1]].reshape(R, dims[l]) for l in range(L) ]
        
        for l in range(L):
            dot(V[l], factors[l], out=A[l])
            dot(V[l].T, P1[l, :, :], out=B[l])
            
        z = matvec(factors, P2, P_VT_W, tmp, result, z, A, B, dims, sum_dims) + damp * Gamma * Q
        z = M * z
        denominator = dot(P.T, z)
        if denominator == 0.0:
            denominator = 1e-6
            
        # Updates.    
        alpha = residualnorm / denominator
        y += alpha * P
        residual_cg -= alpha * z
        residualnorm_new = dot(residual_cg.T, residual_cg)
        beta = residualnorm_new / residualnorm
        residualnorm = residualnorm_new
        P = residual_cg + beta * P

        # Stopping condition.
        if residualnorm <= tol:
            break

    return y, itn, residualnorm


def compute_grad(Tl, factors, P1, g, dims, sum_dims):
    """
    This function computes the gradient of the error function.
    """

    # Initialize first variables.
    L = len(factors)
    R = factors[0].shape[1]

    # Main computations.
    for l in range(L):
        itr = [l for l in reversed(range(L))]
        itr.remove(l)
        M = factors[itr[0]]

        # Compute Khatri-Rao products W^(L) ⊙ ... ⊙ W^(l+1) ⊙ W^(l-1) ⊙ ... ⊙ W^(1).
        for ll in range(L-2):
            tmp = M
            dim1, dim2 = tmp.shape[0], dims[itr[ll+1]]
            M = empty((dim1 * dim2, R), dtype=float64)
            M = mlinalg.khatri_rao(tmp, factors[itr[ll+1]], M)

        N = dot(Tl[l], M)
        gg = dot(factors[l], P1[l])
        g[sum_dims[l]: sum_dims[l+1]] = (gg - N).T.ravel()

    return g


def prepare_data(dims, R):
    """
    Initialize all necessary matrices to keep the values of several computations during the program.
    """

    L = len(dims)

    # Gramians
    Gr = empty((L, R, R), dtype=float64)
    P1 = ones((L, R, R), dtype=float64)
    P2 = ones((L, L, R, R), dtype=float64)

    # Initializations of matrices to receive the results of the computations.
    A = [empty((R, R)) for l in range(L)]
    B = [empty((dims[l], R)) for l in range(L)]
    P_VT_W = empty((R, R), dtype=float64)
    tmp = zeros((R, R), dtype=float64)
    result = [empty((dims[l], R), dtype=float64) for l in range(L)]

    # Matrices to use when constructing the Tikhonov matrix for regularization.
    Gamma = empty(R * sum(dims), dtype=float64)
    gamma = empty((L, R), dtype=float64)

    # Arrays to be used in the Conjugated Gradient.
    sum_dims = array([R * sum(dims[0:l]) for l in range(L+1)])
    M = ones(R * sum(dims), dtype=float64)
    residual_cg = empty(R * sum(dims), dtype=float64)
    P = empty(R * sum(dims), dtype=float64)
    Q = empty(R * sum(dims), dtype=float64)
    z = empty(R * sum(dims), dtype=float64)

    # Arrays to be used in the compute_grad function.
    g = empty(R * sum(dims), dtype=float64)

    data = [Gr, P1, P2, A, B, P_VT_W, tmp, result, Gamma, gamma, sum_dims, M, residual_cg, P, Q, z, g]

    return data


def update_damp(damp, init_damp, old_error, error, residualnorm, it):
    """
    Update rule of the damping parameter for the dGN function.
    """

    if type(init_damp) == list:
        damp = init_damp[it]
    else:
        if old_error != residualnorm:
            gain_ratio = 2 * (old_error - error) / (old_error - residualnorm)
        else:
            gain_ratio = 1.0
        if gain_ratio < 0.75:
            damp = damp / 2
        elif gain_ratio > 0.9:
            damp = 1.5 * damp

    return damp


def gramians(factors, Gr, P1, P2):
    """ 
    Computes all Gramian matrices of the factor matrices. Also it computes all Hadamard products between the 
    different Gramians.
    """

    L = len(factors)
    R = factors[0].shape[1]

    for l in range(L):
        Gr[l, :, :] = dot(factors[l].T, factors[l], out=Gr[l])

    for l in range(L):
        for ll in range(L):
            if l != ll:
                P2[l, ll, :, :] = ones((R, R), dtype=float64)
                itr = [i for i in range(L)]
                itr.remove(l)
                itr.remove(ll)
                for lll in itr:
                    P2[l, ll, :, :] = mlinalg.hadamard(P2[l, ll, :, :], Gr[lll, :, :], P2[l, ll, :, :])
        if l < L-1:
            P1[l, :, :] = mlinalg.hadamard(P2[l, ll, :, :], Gr[ll, :, :], P1[l, :, :])
        else:
            P1[l, :, :] = mlinalg.hadamard(P2[l, 0, :, :], Gr[0, :, :], P1[l, :, :])

    return Gr, P1, P2


def matvec(factors, P2, P_VT_W, tmp, result, z, A, B, dims, sum_dims):
    """
    Makes the matrix-vector computation (Jf^T * Jf)*v.
    """

    L = len(factors)
    R = factors[0].shape[1]

    for l in range(L):
        tmp = 0*tmp
        for ll in range(L):
            if ll != l:
                P_VT_W = mlinalg.hadamard(P2[l, ll, :, :], A[ll], P_VT_W)
                tmp += P_VT_W
        dot(factors[l], tmp, out=result[l])
        result[l] += B[l]
        z[sum_dims[l]: sum_dims[l+1]] = cnv.vec(result[l], z[sum_dims[l]: sum_dims[l+1]], dims[l], R)

    return z


def regularization(factors, Gamma, gamma, P1, dims, sum_dims):
    """
    Computes the Tikhonov matrix Gamma, where Gamma is a diagonal matrix designed specifically to make Jf^T * Jf + Gamma
    diagonally dominant.
    """

    L = len(factors)
    R = factors[0].shape[1]
    for r in range(R):
        gamma[:, r] = abs(P1[:, r, r])
    gamma = np.max(np.abs(P1)) * np.sqrt(gamma)

    for l in range(L):
        for r in range(R):
            Gamma[sum_dims[l] + r*dims[l]: sum_dims[l] + (r+1)*dims[l]] = gamma[l, r]

    return Gamma, gamma


def precond(Gamma, gamma, M, damp, dims, sum_dims):
    """
    This function constructs a preconditioner in order to accelerate the Conjugate Gradient function. It is a diagonal
    preconditioner designed to make Jf^T*J + damp*I a unit diagonal matrix. Since the matrix is diagonally dominant,
    the result will be close to the identity matrix (the equalize function does that). Therefore, it will have its 
    eigenvalues clustered together.
    """

    L, R = gamma.shape
	
    for l in range(L):
        for r in range(R):
            M[sum_dims[l] + r*dims[l]: sum_dims[l] + (r+1)*dims[l]] = \
                gamma[l, r]**2 + damp**2 * Gamma[sum_dims[l] + r*dims[l]: sum_dims[l] + (r+1)*dims[l]]**2

    M = 1 / sqrt(M)

    return M


@njit(nogil=True)
def jacobian(X, Y, Z):
    """
    This function computes the Jacobian matrix Jf of the residual function. This is a dense mnp x r(m+n+p) matrix.
    It is only implemented for third order tensors.
    """

    m, n, p = X.shape[0], Y.shape[0], Z.shape[0]
    r = X.shape[1]
    Jf = zeros((m*n*p, r*(m+n+p)))
    s = 0

    for i in range(m):
        for j in range(n):
            for k in range(p):
                for l in range(r):
                    Jf[s, l*m + i] = -Y[j, l]*Z[k, l]
                    Jf[s, r*m + l*n + j] = -X[i, l]*Z[k, l]
                    Jf[s, r*(m+n) + l*p + k] = -X[i, l]*Y[j, l]
                s += 1

    return Jf


def hessian(Jf):
    """
    Approximate Hessian matrix of the error function.
    """

    H = dot(Jf.T, Jf)
    return H
