package defaultImplementations;

import java.util.ArrayList;

import framework.CheckerInterface;

/**
 * Implementation of
 * {@link framework.CheckerInterface#checkCase(ArrayList, ArrayList, ArrayList)}
 *
 * Assumes an output of strings. Checks whether the number of lines as well as
 * the number of strings per line matches. If a string can be parsed as a
 * double, also checks whether solution and program differ at most by the value
 * specified in {@link #getPrecision()}.
 * The error can be either absolute, absolute and relative or given by a
 * factor with which the solution is multiplied to find suitable bounds.
 * The error mode is specified in {@link #getMode()}.
 *
 * @author Philipp Hoffmann, Chris Pinkau, Chris Mueller
 */
public interface CheckPrecision extends CheckerInterface {
  /**
   * Assumes an output of doubles only. Checks whether the number of lines as
   * well as the number of doubles per line matches. Also checks whether the
   * absolute or relative difference between solution and program is at most
   * the value specified in {@link #getPrecision()}.
   */
  @Override
  default void checkCase(ArrayList<String> in, ArrayList<String> prog, ArrayList<String> out) {
    if (out.size() != prog.size()) {
      reportError("Incorrect number of output lines", out.size(), prog.size());
      return;
    }

    double eps = getPrecision();

    for (int i = 0; i < out.size(); i++) {
      String s1 = out.get(i);
      String s2 = prog.get(i);
      String[] split1 = s1.split("\\s+");
      String[] split2 = s2.split("\\s+");
      if (split1.length != split2.length) {
        reportError("Incorrect number of outputs in line " + i,
            split1.length, split2.length);
        return;
      }
      for (int j = 0; j < split1.length; j++) {
        double outVal = 0;
        double progVal = 0;
        try {
          outVal = Double.parseDouble(split1[j]);
          progVal = Double.parseDouble(split2[j]);
        } catch (NumberFormatException e) {
          if (!split1[j].equals(split2[j])) {
            reportError("Result does not match: ", split1[j], split2[j]);
            return;
          }
        }

        if (Double.isNaN(progVal)) {
          reportError("Result is NaN", outVal, progVal);
          return;
        }

        if (Double.isInfinite(progVal) != Double.isInfinite(outVal)) {
          reportError("Unmatched infinity", outVal, progVal);
          return;
        }

        switch (getMode()) {
          case ABS_ERROR_MODE:
            double absErr = Math.abs(outVal - progVal);
            if (absErr > eps) {
              reportError("Absolute result error too large (abs: " + absErr + ")", outVal, progVal);
              return;
            }
            break;
          case REL_ERROR_MODE:
            double relErr = Math.abs(outVal) > eps ? Math.abs(progVal / outVal - 1) : Math.abs(progVal);
            if (relErr > eps) {
              reportError("Relative result error too large (rel: " + relErr + ")", outVal, progVal);
              return;
            }
            break;
          case ABS_REL_ERROR_MODE:
            double absErr2 = Math.abs(outVal - progVal);
            double relErr2 = Math.abs(outVal) > eps ? Math.abs(progVal / outVal - 1) : Math.abs(progVal);
            if (absErr2 > eps && relErr2 > eps) {
              reportError("Absolute and relative error too large (abs: " + absErr2 + ", rel: " + relErr2 + ")", outVal, progVal);
              return;
            }
            break;
          case FACTOR_BOUNDS_MODE:
            double min = Math.min(outVal, outVal * getPrecision());
            double max = Math.max(outVal, outVal * getPrecision());

            if (progVal < min) {
              reportError("Approximation too small.", outVal, progVal);
            }
            if (progVal > max) {
              reportError("Approximation too large.", outVal, progVal);
            }
            break;
        }

      }
    }
  }

  /**
   * the return value of this function is used as maximum allowed error in
   * {@link #checkCase(ArrayList, ArrayList, ArrayList)}
   *
   * @return the maximum allowed error
   */
  double getPrecision();

  /**
   * Sets the error mode in
   * {@link #checkCase(ArrayList, ArrayList, ArrayList)}
   *
   * @return error acceptance check
   */
  default ERROR_MODE getMode() {
    return ERROR_MODE.ABS_ERROR_MODE;
  }

  /**
   * Enum to determine the error mode of this checker.
   *
   * @author eminenz
   */
  enum ERROR_MODE {
    /**
     * The answer has to be in absolute bounds from the solution
     */
    ABS_ERROR_MODE,
    /**
     * The answer has to be in relative bounds from the solution
     */
    REL_ERROR_MODE,
    /**
     * The answer has to be both in absolute and relative bounds from the solution (default mode)
     */
    ABS_REL_ERROR_MODE,
    /**
     * The answer has to be between <code>solution</code> and <code>solution * precision</code>
     */
    FACTOR_BOUNDS_MODE
  }
}
