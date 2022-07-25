package defaultImplementations;

import java.util.ArrayList;
import java.math.BigInteger;

import framework.CheckerInterface;

/**
 * Implementation of
 * {@link framework.CheckerInterface#checkCase(ArrayList, ArrayList, ArrayList)}
 *
 * Assumes an output of strings. Checks whether the number of lines as well as
 * the number of strings per line matches. If a string can be parsed as a
 * rational, also checks whether solution and program represent the same rational.
 *
 * @author Stefan Toman
 */
public interface CheckRational extends CheckerInterface {
  /**
   * Assumes an output of strings only. Checks whether the number of lines as
   * well as the number of strings per line matches. Also checks whether the
   * strings represent the same rational number if they are not the same.
   */
  @Override
  default void checkCase(ArrayList<String> in, ArrayList<String> prog,
      ArrayList<String> out) {
    if (out.size() != prog.size()) {
      reportError("Incorrect number of output lines", out.size(),
          prog.size());
      return;
    }

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
        compareRationals(split1[j], split2[j]);
      }
    }
  }

  /**
   * This function compare two rational numbers. It checks whether both
   * values are well-formatted rational numbers and whether they represent
   * the same value. It also accpets string that are the same, e.g.
   * "impossible". In case of errors it calls
   * {@link framework.CheckerInterface#reportError(String, Object, Object)}
   *
   * @param s1
   *     The first rational
   * @param s2
   *     The second rational
   *
   * @return whether both values are the same
   */
  default boolean compareRationals(String s1, String s2) {
    if (s1.equals(s2)) {
      return true;
    }
    String[] numdenom1 = s1.split("/");
    String[] numdenom2 = s2.split("/");
    if (numdenom1.length != 2) {
      reportError("Expected a rational number but got something else (should contain exactly one slash)", "rational number", s1);
      return false;
    }
    if (numdenom2.length != 2) {
      reportError("Expected a rational number but got something else (should contain exactly one slash)", "rational number", s2);
      return false;
    }
    BigInteger n1, d1, n2, d2;
    try {
      n1 = new BigInteger(numdenom1[0]);
      d1 = new BigInteger(numdenom1[1]);
    } catch (Exception e) {
      reportError("Expected a rational number but got something else (should consist numbers and a slash only)", "rational number", s1);
      return false;
    }
    try {
      n2 = new BigInteger(numdenom2[0]);
      d2 = new BigInteger(numdenom2[1]);
    } catch (Exception e) {
      reportError("Expected a rational number but got something else (should consist numbers and a slash only)", "rational number", s2);
      return false;
    }
    if (!n1.multiply(d2).equals(n2.multiply(d1))) {
      reportError("Rational numbers do not represent the same value", s1, s2);
      return false;
    }
    return true;
  }
}
