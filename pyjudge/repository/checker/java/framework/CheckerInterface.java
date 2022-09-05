package framework;

import java.util.ArrayList;

/**
 * Specifies all the Methods implemented in the Checkers (or default
 * Implementations) as well as the reportError functions
 *
 * @author Philipp Hoffmann
 */
public interface CheckerInterface {
  /**
   * This method must return true if the input consists of a singular test
   * case, false otherwise.
   */
  boolean isSingularTestCase();

  /**
   * Provided the first line of the input of the test case, this should return
   * the number of non-empty lines that follow in the input and belong to the
   * test case.
   *
   * @param firstLine
   *     The first line of the test case
   *
   * @return The number of non-empty lines to follow
   */
  int inputLines(String firstLine);

  /**
   * This method is to be implemented by the concrete checker to check a
   * single test case excluding header
   *
   * @param in
   *     trimmed non-empty lines of the input
   * @param prog
   *     trimmed non-empty lines of the program output
   * @param out
   *     trimmed non-empty lines of the solution output
   */
  void checkCase(ArrayList<String> in, ArrayList<String> prog, ArrayList<String> out);

  /**
   * HIGHLY UNRECOMMENDED, use only if it is impossible to use
   * {@link #reportError(String, Object, Object)}. prepends the error string
   * with the current test case number and prints the error to stdout
   *
   * @param s
   *     an error message
   */
  void reportError(String s);

  /**
   * prepends the error string with the current test case number and prints
   * the error to stdout including the expected and actual value given
   *
   * @param s
   *     an error message
   * @param expectedValue
   *     the value that should have been in the solution
   * @param actualValue
   *     the value encountered instead in the solution
   */
  void reportError(String s, Object expectedValue, Object actualValue);
}
