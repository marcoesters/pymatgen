# !/usr/bin/env python

"""
This module implements representations of slabs and surfaces.
"""

from __future__ import division

__author__ = "Shyue Ping Ong"
__copyright__ = "Copyright 2014, The Materials Virtual Lab"
__version__ = "0.1"
__maintainer__ = "Shyue Ping Ong"
__email__ = "ongsp@ucsd.edu"
__date__ = "6/10/14"

from fractions import gcd
import math
import numpy as np
import itertools

from pymatgen.core.structure import Structure
from pymatgen import Lattice, Structure

import numpy as np
import copy
import scipy.cluster.hierarchy
import os


def lcm(numbers):
    """Return lowest common multiple."""
    def lcm(a, b):
        return (a * b) / gcd(a, b)
    return reduce(lcm, numbers, 1)


class Slab(Structure):
    """
    Subclass of Structure representing a Slab. Implements additional
    attributes pertaining to slabs.

    .. attribute:: parent

        Parent structure from which Slab was derived.

    .. attribute:: min_slab_size

        Minimum size in angstroms of layers containing atoms

    .. attribute:: min_vac_size

        Minimize size in angstroms of layers containing vacuum

    .. attribute:: scale_factor

        Final computed scale factor that brings the parent cell to the
        surface cell.

    .. attribute:: normal

        Surface normal vector.
    """

    def __init__(self, structure, miller_index, min_slab_size, min_vacuum_size,
                 thresh=0.0001, crit ='distance', lll_reduce=True, standardize = True, shift=0.00000000000001):
        """
        Makes a Slab structure. Note that the code will make a slab with
        whatever size that is specified, rounded upwards. The a and b lattice
        vectors are always in-plane, and the c lattice is always out of plane
        (though not necessarily orthogonal). Enumerates through the different
        terminations in a unit cell in a supercell and inserts a vacuum layer
        at the termination site. Shift parameter allows the user to shift all
        by the shift value in Angstrom. The user can retrieve any of the
        supercells after creating the slab by calling slab_list. For
        example, a = Slab(self, structure, miller_index, min_slab_size,
        min_vacuum_size, thresh). a.slab_list[4] returns the structure
        with a vacuum layer in the fourth termination site from teh origin.
        Similarly, a.term_coords[4] will return the sites with species and
        coordinates in a surface termination. To see if the program generated
        the correct number of terminations, run len(a.slab_list).

        Args:
            structure (Structure): Initial input structure.
            miller_index ([h, k, l]): Miller index of plane parallel to
                surface. Note that this is referenced to the input structure. If
                you need this to be based on the conventional cell,
                you should supply the conventional structure.
            min_slab_size (float): In Angstroms
            min_vacuum_size (float): In Angstroms
            thresh (float): Threshold parameter in fclusterdata in order to determine
                the number of terminations to be found. If the user knows how many
                terminations should be generated by the program, they can enter an
                appropriate value for this parameter. Values range from 0-1 with
                smaller values cluster sites closer together as being part of a
                termination.
            crit (str): The criterion to set for fclusterdata (see fcluster for
                description).
            lll_reduce (bool): Whether to perform an LLL reduction on the
                eventual structure.
            standardize (bool): Whether to center the slab in the cell with equal
                vacuum spacing from the top and bottom.
            shift (float): In Angstroms (shifting the origin)
        """
        latt = structure.lattice
        d = reduce(gcd, miller_index)
        miller_index = [int(i / d) for i in miller_index]
        #Calculate the surface normal using the reciprocal lattice vector.
        recp = latt.reciprocal_lattice_crystallographic
        normal = recp.get_cartesian_coords(miller_index)
        normal /= np.linalg.norm(normal)

        slab_scale_factor = []
        non_orth_ind = []
        eye = np.eye(3, dtype=np.int)
        dist = float('inf')
        for i, j in enumerate(miller_index):
            if j == 0:
                # Lattice vector is perpendicular to surface normal, i.e.,
                # in plane of surface. We will simply choose this lattice
                # vector as one of the basis vectors.
                slab_scale_factor.append(eye[i])
            else:
                #Calculate projection of lattice vector onto surface normal.
                d = abs(np.dot(normal, latt.matrix[i]))
                non_orth_ind.append(i)
                if d < dist:
                    latt_index = i
                    dist = d

        if len(non_orth_ind) > 1:
            lcm_miller = lcm([miller_index[i] for i in non_orth_ind])
            for i, j in itertools.combinations(non_orth_ind, 2):
                l = [0, 0, 0]
                l[i] = -int(round(lcm_miller / miller_index[i]))
                l[j] = int(round(lcm_miller / miller_index[j]))
                slab_scale_factor.append(l)
                if len(slab_scale_factor) == 2:
                    break

        nlayers_slab = int(math.ceil(min_slab_size / dist))
        nlayers_vac = int(math.ceil(min_vacuum_size / dist))
        nlayers = nlayers_slab + nlayers_vac
        slab_scale_factor.append(eye[latt_index] * nlayers)

        slab = structure.copy()

        slab.make_supercell(slab_scale_factor)
        new_sites = []
        for site in slab:
            if shift <= np.dot(site.coords, normal) < nlayers_slab * dist + \
                    shift:
                new_sites.append(site)
        slab = Structure.from_sites(new_sites)

        if lll_reduce:
            lll_slab = slab.copy(sanitize=True)
            mapping = lll_slab.lattice.find_mapping(slab.lattice)
            slab_scale_factor = np.dot(mapping[2], slab_scale_factor)
            slab = lll_slab

        n = 0
        term_slab = slab.copy()
        c = term_slab.lattice.c
        # For loop moves all sites down to compensate for the space opened up by the shift
        for site in term_slab:
            index = []
            index.append(n)
            term_slab.translate_sites(index, [0, 0, -shift/c])
            n+=1

        el = term_slab.species
        org_coords = term_slab.frac_coords.tolist()
        new_coord, b = [], []

#        for i in org_coords:
#            i[2] = (i[2]*c)/term_slab.lattice.c

        for i in term_slab.frac_coords:
            b.append(i[2])
            new_coord.append(b)
            b = []

        # Clusters sites together that belong in the same termination surface based on their position in the
        # c direction. Also organizes sites by ascending order from teh origin along the c direction. How close
        # the sites have to be to belong in the same termination surface depends on the user input thresh.
        tracker_index = scipy.cluster.hierarchy.fclusterdata(new_coord, thresh, criterion= crit)
        new_coord, tracker_index, org_coords, el = zip(*sorted(zip(new_coord, tracker_index, org_coords, el)))

# Creates a list (term_index) that tells us which at which site does a termination begin. For 1 unit cell.
        term_index = []
        gg = 0
        for i in range(0, len(term_slab)):
            gg +=1
            if i == len(term_slab) - 1:
                term_index.append(i)
            else:
                if tracker_index[i] != tracker_index[i+1]:
                    term_index.append(i)
            if gg == len(structure):
                    break

        slab_list, term_coords = [], []
        a, i = 0, 0
        new_slab = Structure(term_slab.lattice, el, org_coords)
        term_scale = nlayers_vac*dist

        for iii in range(0, len(term_index)):
            y = []
            alt_slab = new_slab.copy()

            for ii in range(0, len(alt_slab)):
                index = []
                index.append(ii)

                if alt_slab.frac_coords[ii][2] > alt_slab.frac_coords[term_index[iii]][2]:
                    alt_slab.translate_sites(index, [0, 0, term_scale/(new_slab.lattice.c)])

            if standardize:
                index = []
                for f in range(0, len(alt_slab)):
                    index.append(f)
                    standard_shift = -(alt_slab.frac_coords[term_index[iii]][2] +
                                       (0.5*term_scale)/alt_slab.lattice.c)

                if alt_slab.frac_coords[f][2] > alt_slab.frac_coords[term_index[iii]][2]:
                    alt_slab.translate_sites(index, [0, 0, standard_shift])
                else:
                    alt_slab.translate_sites(index, [0, 0, 1+standard_shift])


            slab_list.append(alt_slab)

            for iv in range(a, term_index[iii] + 1):
                y.append(slab_list[i][iv])

            i += 1
            term_coords.append(y)
            a = term_index[iii]+1

        self.min_slab_size = min_slab_size
        self.nlayers_slab = nlayers_slab
        self.min_vac_size = min_vacuum_size
        self.slab_list = slab_list # Holds a list of Structure objects of slabs with different terminations
        self.parent = structure
        self.miller_index = miller_index
        self.term_index = term_index
        self.term_coords = term_coords # Holds the corresponding list of sites on the surface terminations
        self.thresh = thresh
        self.shift = shift
        self.scale_factor = np.array(slab_scale_factor)
        self.normal = normal

        super(Slab, self).__init__(
            slab.lattice, slab.species_and_occu, slab.frac_coords,
            site_properties=slab.site_properties)

    @property
    def surface_area(self):
        m = self.lattice.matrix
        return np.linalg.norm(np.cross(m[0], m[1]))

    @classmethod
    def adsorb_atom(cls, structure_a, site_a, atom, distance,
                    surface=[0, 0, 1], xyz=0):
        """
        Gets the structure of single atom adsorption.

        Args:
        structure_a: the slab structure for adsorption
        site_a:  given sites for adsorption.
             default(xyz=0): site_a = [a, b, c], within [0,1];
             xyz=1: site_a = [x, y, z], in Angstroms.
        atom: adsorbed atom species
        distance: between centers of the adsorbed atom and the given site.
             in Angstroms
        surface: direction of the surface where atoms are adsorbed to
             default: surface = [0, 0, 1]
        xyz: default is 0. 1 means site_a = [x, y, z], in Angstroms.

        """
        from pymatgen.transformations.site_transformations import \
            InsertSitesTransformation

        lattice_s = structure_a.lattice
        abc_s = lattice_s.abc
        # a123_s = lattice_s.matrix
        b123_s = lattice_s.inv_matrix.T
        # print surface
        vector_o = np.dot(surface, b123_s)
        print vector_o
        lens_v = np.sqrt(np.dot(vector_o, vector_o.T))
        V_o = vector_o / lens_v * distance

        if xyz == 0:
            # site_a = [a, b, c]
            for i in xrange(3):
                if site_a[i]> 1 or site_a[i] < 0:
                    raise ValueError("site_a is outsite the cell.")
            site_abc = V_o / abc_s + site_a
        else:
            # site_a = [x, y, z]
            for i in xrange(3):
                if site_a[i] > abc_s[i]:
                    raise ValueError("sites_a is outside the cell.")
            site_a1 = np.array(site_a)

            # convert to a1, a2, a3
            #< site_a2 = np.dot(a123_s, site_a1.T) / abc_s
            #< site_abc = (V_o+site_a2) / abc_s
            site_a2 = np.dot(b123_s, site_a1.T)

            site_abc = V_o/abc_s+site_a2

        for i in xrange(3):
            if site_abc[i] < 0 or site_abc[i] > 1:
                raise ValueError("wrong distance, atom will be outside the cell.")


        print 'add_site:', site_abc, atom

        ist = InsertSitesTransformation(species=atom, coords=[site_abc])
        structure_ad = ist.apply_transformation(structure_a)

        return structure_ad


import unittest
from pymatgen.core.lattice import Lattice
from pymatgen.io.smartio import CifParser
from pymatgen import write_structure

# To run this test, it is assumed that the pymatgen folder is in your home directory
def get_path(path_str):
    file_name = "pymatgen/pymatgen/core/tests/surface tests/" + path_str
    path = os.path.join(os.path.expanduser("~"), file_name)
    return path

class SlabTest(unittest.TestCase):

    def setUp(self):
        self.cu = Structure(Lattice.cubic(3), ["Cu", "Cu", "Cu", "Cu"],
                            [[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5],
                             [0, 0.5, 0.5]])

        self.lifepo4 = Structure(Lattice.orthorhombic(10.332, 6.01, 4.787),
                                 ["Li", "Li", "Li", "Li", "Fe", "Fe", "Fe", "Fe", "P", "P", "P", "P", "O",
                                  "O", "O", "O", "O", "O", "O", "O", "O", "O", "O", "O", "O", "O", "O", "O"],
                                 [[0.5, 0, 0.5], [0, 0.5, 0], [0.5, 0.5, 0.5], [0, 0, 0], [0.78221, 0.25, 0.52527],
                                  [0.28221, 0.25, 0.97473], [0.21779,  0.75,     0.47473], [0.71779,  0.75,     0.02527],
                                  [0.59485,  0.25,     0.08079], [.09485,  0.25,     0.41921], [0.40515,  0.75,     0.91921],
                                  [0.90515,  0.75,     0.58079], [0.5968,   0.25,     0.757  ], [0.0968,   0.25,     0.743  ],
                                  [0.4032,   0.75,     0.243  ], [0.9032,   0.75,     0.257  ], [0.9567,   0.25,     0.294  ],
                                  [0.4567,   0.25,     0.206  ], [0.0433,   0.75,     0.706  ], [0.5433,   0.75,     0.794  ],
                                  [0.66567,  0.0466,   0.2153 ], [0.16567,  0.4534,   0.2847 ], [0.33433,  0.5466,   0.7847 ],
                                  [0.83433,  0.9534,   0.7153 ], [0.33433,  0.9534,   0.7847 ], [0.83433,  0.5466,   0.7153 ],
                                  [0.66567,  0.4534,   0.2153 ], [0.16567,  0.0466,   0.2847 ]])

        self.zno = Structure(Lattice.from_parameters(3.253, 3.253, 5.213, 90, 90, 120), ["Zn", "Zn", "O", "O"],
                             [[0.6667, 0.3334, 0.5], [0.3333, 0.6666, 0],
                              [0.6667, 0.3334, 0.882], [0.3333, 0.6666, 0.382]])

        #Zn_O = CifParser(get_path("001_terminations/ZnO-wz.cif"))
        #self.zno = (Zn_O.get_structures(primitive = False)[0])
        #Li_Fe_PO4  = CifParser(get_path("001_terminations/LiFePO4.cif"))
        #self.lifepo4= (Li_Fe_PO4.get_structures(primitive = False)[0])

    def test_init(self):
        for hkl in itertools.product(xrange(4), xrange(4), xrange(4)):
            if any(hkl):
                ssize = 6
                vsize = 10
                s = Slab(self.cu, hkl, ssize, vsize)
                if hkl == [0, 1, 1]:
                    self.assertEqual(len(s), 13)
                    self.assertAlmostEqual(s.surface_area, 12.727922061357855)
                manual = self.cu.copy()
                manual.make_supercell(s.scale_factor)
                self.assertEqual(manual.lattice.lengths_and_angles,
                                 s.lattice.lengths_and_angles)

        # # For visual debugging
        # from pymatgen import write_structure
        # write_structure(s.parent, "cu.cif")
        # write_structure(s, "cu_slab_%s_%.3f_%.3f.cif" %
        #                  (str(hkl), ssize, vsize))

    def test_adsorb_atom(self):
        s001 = Slab(self.cu,[0, 0, 1], 5, 5)
        # print s001
        # O adsorb on 4Cu[0.5, 0.5, 0.25], abc = [3, 3, 12]
        # 1. test site_a = abc input
        s001_ad1 = Slab.adsorb_atom(structure_a=s001, site_a=[0.5, 0.5, 0.25], atom= ['O'],
                                    distance=2)
        self.assertEqual(len(s001_ad1), 9)
        for i in xrange(len(s001_ad1)):
            if str(s001_ad1[i].specie) == 'O':
                print s001_ad1[i].frac_coords
                self.assertAlmostEqual(s001_ad1[i].a, 0.5)
                self.assertAlmostEqual(s001_ad1[i].b, 0.5)
                self.assertAlmostEqual(s001_ad1[i].c, 0.4166667)
        self.assertEqual(s001_ad1.lattice.lengths_and_angles,
                                 s001.lattice.lengths_and_angles)
        # 2. test site_a = xyz input
        s001_ad2 = Slab.adsorb_atom(structure_a=s001, site_a=[1.5, 1.5, 3], atom= ['O'],
                                    distance=2, xyz=1)
        self.assertEqual(len(s001_ad2), 9)
        for i in xrange(len(s001_ad2)):
            if str(s001_ad2[i].specie) == 'O':
                print s001_ad2[i].frac_coords
                self.assertAlmostEqual(s001_ad2[i].a, 0.5)
                self.assertAlmostEqual(s001_ad2[i].b, 0.5)
                self.assertAlmostEqual(s001_ad2[i].c, 0.4166667)

    def test_make_terminations(self):

        hkl001 = [0, 0, 1]
        z001 = Slab(self.zno, hkl001, 10, 3, 0.025, shift = 2)
        l001 = Slab(self.lifepo4, hkl001, 10, 10, 0.0031)
        l001_shift = Slab(self.lifepo4, hkl001, 10, 10, shift = 3)

        hkl100 = [1, 0, 0]
        z100 = Slab(self.zno, hkl100, 10, 5, 0.01)
        l100 = Slab(self.lifepo4, hkl100, 30, 10, 0.0031)

        m = [z001, l001, z100, l100]

        fileName = [get_path("001_terminations/ZnO-wz.cif"),
                    get_path("001_terminations/LiFePO4.cif"),
                    get_path("100_terminations/ZnO-wz.cif"),
                    get_path("100_terminations/LiFePO4.cif")]

        for i in range(0, len(fileName)):
            Name = fileName[i][:-4] + "_%s_slab %s_vac %s_threshold %s_shift %s_#" \
                                      %(str(m[i].miller_index),
                                        m[i].min_slab_size,
                                        m[i].min_vac_size,
                                        m[i].thresh,
                                        m[i].shift)
            fileType = ".cif"

            # For visual debugging
            for ii in range(0, len(m[i].slab_list)):
                name_num = str(ii)
                newFile = Name + name_num + fileType
                write_structure(m[i].slab_list[ii], newFile)

                # Compares the newly created structure to ones that were already made for checking sites are being
                # translated correctly. Optional test can be turned on. Test turned off by default to save processing.
                #test_comp = CifParser(get_path("tests" + newFile[+73:]))
                #self.compare_structure = (test_comp.get_structures(primitive = False)[0])
                #test_new = CifParser(newFile)
                #self.new_structure = (test_new.get_structures(primitive = False)[0])
                #self.assertEqual(self.compare_structure, self.new_structure)

            # Prints the coordinates and the species of each atom along with the number of atoms on a
            # surface termination site
            for iii in range(0, len(m[i].term_coords)):
                print(m[i].term_coords[iii])
                print("%s atoms in this termination surface." %(len(m[i].term_coords[iii])))

            print(" ")
        # Checks to see if the program generates the number of terminations we would expect it to
        self.assertEqual(len(z001.slab_list), 4)
        self.assertEqual(len(z100.slab_list), 2)
        self.assertEqual(len(l001.slab_list), 16)
        self.assertEqual(len(l100.slab_list), 18)

        # Checks to see if the vacuum and slab size and shift conforms to user input
        s = (l100.slab_list[0].frac_coords[len(l100.slab_list[0].frac_coords)-1][2] -
             l100.slab_list[0].frac_coords[1][2])*l100.slab_list[0].lattice.c
        v = l100.slab_list[0].lattice.c - s
        self.assertAlmostEqual(v, l100.min_vac_size, places=-1)
        self.assertAlmostEqual(s, l100.min_slab_size, places=1)
        shift = (l001.slab_list[1].frac_coords[24][2] -
                 l001_shift.slab_list[2].frac_coords[8][2])*l001.slab_list[0].lattice.c
        self.assertAlmostEqual(shift, l001_shift.shift, places=0)



if __name__ == "__main__":
    unittest.main()


