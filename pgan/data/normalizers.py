#-*- coding: utf-8 -*-

from collections import OrderedDict
from pgan.models import MultiVariable

class Normalizer:
    """
    Simple convenience class that performs transformations to/from normalized values.
    Here, we use the norm range [-1, 1] for pos=False or [0, 1] for pos=True.
    """

    def __init__(self, xmin, xmax, pos=False):
        self.xmin = xmin
        self.xmax = xmax
        self.denom = xmax - xmin
        self.pos = pos

    def __call__(self, x):
        """
        Alias for Normalizer.forward()
        """
        return self.forward(x)

    def forward(self, x):
        """
        Normalize data.
        """
        if self.pos:
            return (x - self.xmin) / self.denom
        else:
            return 2.0 * (x - self.xmin) / self.denom - 1.0

    def inverse(self, xn):
        """
        Un-normalize data.
        """
        if self.pos:
            return self.denom * xn + self.xmin
        else:
            return 0.5 * self.denom * (xn + 1.0) + self.xmin


class MultiNormalizer:
    """
    Encapsulates multiple Normalizer objects hashed by name.
    """

    def __init__(self, **kwargs):
        self.normalizers = OrderedDict()
        for name, norm in kwargs.items():
            assert isinstance(norm, Normalizer), 'Must pass in Normalizer as value'
            self.normalizers[name] = norm

    def __call__(self, multi_var):
        """
        Alias for MultiNormalizer.forward().
        """
        return self.forward(multi_var)

    def forward(self, multi_var):
        """
        Performs normalization (forward pass) of MultiVariable instance. Returns a
        new MultiVariable instance.
        """
        # Initialize output variable
        out = MultiVariable()

        # Iterate over variable names
        for varname, normalizer in self.normalizers.items():
            out[varname] = normalizer(multi_var[varname])

        # Done
        return out

    def inverse(self, multi_var):
        """
        Performs inverse normalization (un-normalize) of MultiVariable instance. Returns a
        new MultiVariable instance.
        """
        # Initialize output variable
        out = MultiVariable()

        # Iterate over variable names
        for varname, normalizer in self.normalizers.items():
            out[varname] = normalizer.inverse(mult_var[varname])

        # Done
        return out


# end of file
