package framework;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.InputMismatchException;

/**
 * Abstract Checker, implements syntactic checks.
 *
 * @author Philipp Hoffmann
 */
public abstract class AbstractChecker implements CheckerInterface {

  /**
   * The current test case, used in {@link #reportError(String)} and
   * {@link #checkAndRemoveCaseHeader(String)}.
   */
  private int testCase = 1;

  /**
   * Checks all test cases. Removes empty lines as well as the case header,
   * then passes the remaining lines to
   * {@link CheckerInterface#checkCase(ArrayList, ArrayList, ArrayList)}.
   */
  public final void check() throws IOException {
    if (inputSc == null || programSc == null || outputSc == null) {
      throw new IllegalStateException("Stream not set");
    }

    int t;
    if (isSingularTestCase()) {
      t = 1;
    } else {
      t = Integer.parseInt(nextNonEmptyLine(inputSc));
    }

    String firstLineProgram = null;
    String firstLineSolution = null;

    for (testCase = 1; testCase <= t; testCase++) {

      ArrayList<String> inputLines = new ArrayList<>();

      // read input lines until the test case ends
      String firstLine = nextNonEmptyLine(inputSc);
      if (firstLine == null) {
        reportError("Unexpected end of input");
        throw new InputMismatchException("Unexpected end of input");
      }
      inputLines.add(firstLine);

      int lines = inputLines(firstLine);
      for (int i = 0; i < lines; i++) {
        String line = nextNonEmptyLine(inputSc);
        if (line == null) {
          reportError("Unexpected end of input");
          throw new InputMismatchException("Unexpected end of input");
        }
        inputLines.add(line);
      }


      // read program lines until next case header or EOF
      ArrayList<String> programLines = new ArrayList<>();

      if (firstLineProgram == null) {
        firstLineProgram = nextNonEmptyLine(programSc);
      }
      // case header
      firstLineProgram = checkAndRemoveCaseHeader(firstLineProgram);

      boolean processCase = true;
      // if case header did not match, ignore this test case
      if (firstLineProgram == null) {
        reportError("Could not find case header for case " + testCase);
        throw new InputMismatchException("Could not find case header for case " + testCase);
      } else if (firstLineProgram.length() != 0) {
        programLines.add(firstLineProgram.trim());
      }

      String currLine = nextNonEmptyLine(programSc);
      while (currLine != null && !currLine.startsWith("Case #")) {
        programLines.add(currLine);
        currLine = nextNonEmptyLine(programSc);
      }

      // if there is more
      if (currLine != null) {
        // save header for next test case
        firstLineProgram = currLine;
      }


      // read solution lines until next case header or EOF
      ArrayList<String> outputLines = new ArrayList<>();

      if (firstLineSolution == null) {
        firstLineSolution = nextNonEmptyLine(outputSc);
      }
      // case header from last time
      firstLineSolution = checkAndRemoveCaseHeader(firstLineSolution);

      // should never happen
      if (firstLineSolution == null) {
        reportError("Testcase output file case header incorrect!");
        throw new InputMismatchException("Error in testcase output");
      }
      firstLineSolution = firstLineSolution.trim();

      if (firstLineSolution.length() != 0) {
        outputLines.add(firstLineSolution);
      }

      currLine = nextNonEmptyLine(outputSc);
      while (currLine != null && !currLine.startsWith("Case #")) {
        outputLines.add(currLine);
        currLine = nextNonEmptyLine(outputSc);
      }

      // if there is more
      if (currLine != null) {
        // save header for next test case
        firstLineSolution = currLine;
      }
      try {
        checkCase(inputLines, programLines, outputLines);
      } catch (Exception e) {
        reportError("Exception was thrown:");
        e.printStackTrace(System.out);
      }
    }
  }

  /**
   * HIGHLY UNRECOMMENDED, use only if it is impossible to use
   * {@link #reportError(String, Object, Object)}. Prepends the error string
   * with the current test case number and prints the error to stdout.
   *
   * @param s
   *     an error message
   */
  public final void reportError(String s) {
    System.out.format("Testcase %d: %s%n", testCase, s);
  }

  /**
   * prepends the error string with the current test case number and prints
   * the error to stdout including the expected and actual value given.
   *
   * @param s
   *     an error message
   * @param expectedValue
   *     the value that should have been in the solution
   * @param actualValue
   *     the value encountered instead in the solution
   */
  public final void reportError(String s, Object expectedValue,
      Object actualValue) {
    System.out.format("Testcase %d: %s%n", testCase, s);
    System.out.println("Expected: " + expectedValue);
    System.out.println("Value was: " + actualValue);
  }

  /**
   * Returns the next trimmed non-empty line or null if there is none.
   */
  private String nextNonEmptyLine(BufferedReader br) throws IOException {
    String line = br.readLine();
    if (line != null) {
      line = line.trim();
    }
    while (line != null && line.length() == 0) {
      line = br.readLine();
      if (line != null) {
        line = line.trim();
      }
    }
    return line;
  }

  /**
   * Checks if the line starts with "Case #%d:" where %d is the current test
   * case. Returns the trimmed rest of the line, or null, if the case header
   * did not match the expected one.
   *
   * @param firstLine
   *     the first line of the test case
   *
   * @return the remainder of the line (may have length 0).
   */
  private String checkAndRemoveCaseHeader(String firstLine) {
    if (firstLine == null) {
      reportError("Case header seems to be missing");
      return null;
    }
    if (!firstLine.startsWith("Case #" + testCase + ":")) {
      String beginning = firstLine;
      if (firstLine.length() > 10) {
        beginning = firstLine.substring(10) + "_";
      }
      reportError("Incorrect case header", "Case #" + testCase + ":",
          beginning);
      return null;
    }
    return firstLine.substring(firstLine.indexOf(':') + 1).trim();
  }

  private BufferedReader inputSc;
  private BufferedReader programSc;
  private BufferedReader outputSc;

  public void setTestcaseInput(InputStream is) {
    inputSc = new BufferedReader(new InputStreamReader(is));
  }

  public void setProgramSc(InputStream is) {
    programSc = new BufferedReader(new InputStreamReader(is));
  }

  public void setTestcaseOutputSc(InputStream is) {
    outputSc = new BufferedReader(new InputStreamReader(is));
  }
}
