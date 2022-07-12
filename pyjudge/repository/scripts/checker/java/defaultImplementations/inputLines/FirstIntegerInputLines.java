package defaultImplementations.inputLines;

import java.util.InputMismatchException;
import java.util.Scanner;

import framework.CheckerInterface;

/**
 * Implementation of {@link framework.CheckerInterface#inputLines(String)}
 *
 * Interprets the first token in the first line as integer n and expects n more
 * lines of input
 *
 * @author Philipp Hoffmann
 */
public interface FirstIntegerInputLines extends CheckerInterface {
  /**
   * Interprets the first token in the first line as integer n and expects n
   * more lines of input
   */
  @Override
  default int inputLines(String firstLine) {
    Scanner sc = new Scanner(firstLine);
    if (sc.hasNextInt()) {
      int lines = sc.nextInt();
      sc.close();
      return lines;
    } else {
      sc.close();
      throw new InputMismatchException("No integer in first line!");
    }
  }
}
